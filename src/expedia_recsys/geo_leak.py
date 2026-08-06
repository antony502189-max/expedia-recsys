from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from expedia_recsys.competition import (
    DEFAULT_BATCH_SIZE,
    _batch_ranges,
    _create_history,
    _create_validation_rows,
    _row_bounds,
)
from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect, sql_path

if TYPE_CHECKING:
    import duckdb


@dataclass(frozen=True, slots=True)
class GeoSource:
    source_id: int
    name: str
    keys: tuple[str, ...]
    decimals: int | None
    weight: float


@dataclass(frozen=True, slots=True)
class GeoMetrics:
    cutoff: str
    validation_rows: int
    distance_rows: int
    champion_map_at_5: float
    geo_map_at_5: float
    overlay_map_at_5: float
    coverage: float
    use_rate: float
    min_confidence: float
    min_booking_support: int
    source_metrics: list[dict[str, object]]


SOURCES: tuple[GeoSource, ...] = (
    GeoSource(
        1,
        "exact_full_geo",
        (
            "user_location_country",
            "user_location_region",
            "user_location_city",
            "hotel_market",
        ),
        None,
        26.0,
    ),
    GeoSource(
        2,
        "full_geo_round3",
        (
            "user_location_country",
            "user_location_region",
            "user_location_city",
            "hotel_market",
        ),
        3,
        21.0,
    ),
    GeoSource(
        3,
        "destination_city_round3",
        ("user_location_city", "srch_destination_id", "hotel_market"),
        3,
        17.0,
    ),
    GeoSource(
        4,
        "full_geo_round2",
        (
            "user_location_country",
            "user_location_region",
            "user_location_city",
            "hotel_market",
        ),
        2,
        14.0,
    ),
    GeoSource(
        5,
        "destination_city_round2",
        ("user_location_city", "srch_destination_id", "hotel_market"),
        2,
        11.0,
    ),
    GeoSource(
        6,
        "city_market_round3",
        ("user_location_city", "hotel_market"),
        3,
        8.0,
    ),
)
CONFIDENCE_GRID = (0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)
SUPPORT_GRID = (1, 2, 3, 5, 10)


def _distance(source: GeoSource, alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    if source.decimals is None:
        return f"{prefix}orig_destination_distance_key"
    return f"ROUND({prefix}orig_destination_distance, {source.decimals})"


def _lookup_name(source: GeoSource) -> str:
    return f"geo_top_{source.name}"


def _build_lookups(con: duckdb.DuckDBPyConnection) -> None:
    print("[geo-leak] building exact and fuzzy lookups")
    for source in SOURCES:
        keys = ", ".join(source.keys)
        select_keys = f"{keys}," if keys else ""
        partition = f"{keys}, distance_token"
        group_by = f"{keys}, distance_token, hotel_cluster"
        nulls = [f"{key} IS NOT NULL" for key in source.keys]
        nulls.append(
            "orig_destination_distance_key IS NOT NULL"
            if source.decimals is None
            else "orig_destination_distance IS NOT NULL"
        )
        print(f"[geo-leak] source: {source.name}")
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE {_lookup_name(source)} AS
            WITH scores AS (
                SELECT
                    {select_keys}
                    {_distance(source)} AS distance_token,
                    hotel_cluster,
                    SUM(event_weight * GREATEST(cnt, 1)) AS raw_score,
                    SUM(
                        CASE WHEN is_booking = 1 THEN GREATEST(cnt, 1) ELSE 0 END
                    ) AS booking_support
                FROM competition_history
                WHERE {' AND '.join(nulls)}
                GROUP BY {group_by}
            ),
            ranked AS (
                SELECT
                    *,
                    raw_score / NULLIF(
                        SUM(raw_score) OVER (PARTITION BY {partition}), 0.0
                    ) AS purity,
                    ROW_NUMBER() OVER (
                        PARTITION BY {partition}
                        ORDER BY raw_score DESC, booking_support DESC, hotel_cluster
                    ) AS source_rank
                FROM scores
            )
            SELECT * FROM ranked WHERE source_rank <= 5
            """
        )


def _source_select(source: GeoSource, start: int, stop: int) -> str:
    conditions = [f"q.{key} = t.{key}" for key in source.keys]
    conditions.append(f"{_distance(source, 'q')} = t.distance_token")
    return f"""
    SELECT
        q.row_id,
        t.hotel_cluster,
        {source.source_id}::TINYINT AS source_id,
        t.source_rank::SMALLINT AS source_rank,
        t.purity::FLOAT AS purity,
        t.booking_support::INTEGER AS booking_support,
        (
            {source.weight}
            * (0.8 * t.purity + 0.2 / t.source_rank)
            * (1.0 + 0.08 * LN(1.0 + t.booking_support))
        )::FLOAT AS signal
    FROM competition_query_rows q
    JOIN {_lookup_name(source)} t ON {' AND '.join(conditions)}
    WHERE q.row_id >= {start} AND q.row_id < {stop}
    """


def _create_batch(con: duckdb.DuckDBPyConnection, start: int, stop: int) -> None:
    union = "\nUNION ALL\n".join(
        _source_select(source, start, stop) for source in SOURCES
    )
    con.execute("DROP TABLE IF EXISTS geo_events")
    con.execute("DROP TABLE IF EXISTS geo_candidates")
    con.execute(f"CREATE TEMP TABLE geo_events AS {union}")
    con.execute(
        """
        CREATE TEMP TABLE geo_candidates AS
        WITH combined AS (
            SELECT
                row_id,
                hotel_cluster,
                SUM(signal) AS score,
                MAX(purity) AS confidence,
                MAX(booking_support) AS booking_support,
                FIRST(source_id ORDER BY signal DESC, source_id) AS source_id
            FROM geo_events
            GROUP BY row_id, hotel_cluster
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY row_id
                    ORDER BY score DESC, confidence DESC, hotel_cluster
                ) AS final_rank
            FROM combined
        )
        SELECT * FROM ranked WHERE final_rank <= 5
        """
    )


def _parse_prediction(value: object) -> list[int]:
    result: list[int] = []
    for token in str(value or "").split():
        try:
            cluster = int(token)
        except ValueError:
            continue
        if 0 <= cluster <= 99 and cluster not in result:
            result.append(cluster)
    return result[:5]


def _merge_top5(primary: Sequence[int], fallback: Sequence[int]) -> list[int]:
    result: list[int] = []
    for cluster in (*primary, *fallback):
        value = int(cluster)
        if value not in result:
            result.append(value)
        if len(result) == 5:
            break
    return result


def _reciprocal_rank(actual: int, predictions: Sequence[int]) -> float:
    for rank, cluster in enumerate(predictions[:5], start=1):
        if int(cluster) == int(actual):
            return 1.0 / rank
    return 0.0


def _thresholds() -> Iterator[tuple[float, int]]:
    for confidence in CONFIDENCE_GRID:
        for support in SUPPORT_GRID:
            yield confidence, support


def _load_champion(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    validation_rows: int,
) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Champion predictions are missing: {path}. Run ranker-validate first."
        )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE geo_champion AS
        SELECT
            TRY_CAST(row_id AS BIGINT) AS row_id,
            TRY_CAST(actual_hotel_cluster AS SMALLINT) AS actual_hotel_cluster,
            hotel_cluster::VARCHAR AS predictions
        FROM read_csv_auto(
            '{sql_path(path)}', header = true, all_varchar = true
        )
        WHERE TRY_CAST(row_id AS BIGINT) IS NOT NULL
        """
    )
    rows = int(con.execute("SELECT COUNT(*) FROM geo_champion").fetchone()[0])
    if rows != validation_rows:
        raise RuntimeError(
            f"Champion rows do not match validation: {rows:,} != {validation_rows:,}."
        )
    mismatches = int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM geo_champion c
            JOIN competition_query_rows q USING (row_id)
            WHERE c.actual_hotel_cluster <> q.hotel_cluster
            """
        ).fetchone()[0]
    )
    if mismatches:
        raise RuntimeError(f"Champion row alignment failed: {mismatches:,} mismatches.")


def validate_geo_leak(
    paths: ProjectPaths,
    *,
    cutoff: date = date(2014, 8, 1),
    champion_path: Path | None = None,
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> GeoMetrics:
    train_path = paths.processed_dir / "train.parquet"
    if not train_path.exists():
        raise FileNotFoundError("train.parquet is missing. Run prepare first.")
    paths.ensure_directories()
    champion_path = champion_path or (
        paths.artifacts_dir / "ranker_validation_predictions.csv"
    )
    output_path = paths.artifacts_dir / "geo_leak_validation_metrics.json"
    con = connect(
        paths.processed_dir / "geo_leak_validation.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )
    try:
        _create_history(con, train_path, cutoff)
        _create_validation_rows(con, train_path, cutoff)
        _build_lookups(con)
        start, stop, validation_rows = _row_bounds(con)
        distance_rows = int(
            con.execute(
                """
                SELECT COUNT(*) FROM competition_query_rows
                WHERE orig_destination_distance IS NOT NULL
                """
            ).fetchone()[0]
        )
        _load_champion(con, champion_path, validation_rows)

        thresholds = list(_thresholds())
        score_sums = {item: 0.0 for item in thresholds}
        use_counts = {item: 0 for item in thresholds}
        champion_sum = 0.0
        geo_sum = 0.0
        covered = 0
        source_totals = {
            source.source_id: {"covered": 0, "top1": 0, "hit5": 0}
            for source in SOURCES
        }
        ranges = list(_batch_ranges(start, stop, batch_size))
        started = time.perf_counter()

        for number, (batch_start, batch_stop) in enumerate(ranges, start=1):
            _create_batch(con, batch_start, batch_stop)
            for source_id, source_covered, top1, hit5 in con.execute(
                """
                WITH per_query AS (
                    SELECT
                        e.source_id,
                        e.row_id,
                        MAX(
                            CASE WHEN e.source_rank = 1
                             AND e.hotel_cluster = q.hotel_cluster THEN 1 ELSE 0 END
                        ) AS top1,
                        MAX(
                            CASE WHEN e.hotel_cluster = q.hotel_cluster THEN 1 ELSE 0 END
                        ) AS hit5
                    FROM geo_events e
                    JOIN competition_query_rows q USING (row_id)
                    GROUP BY e.source_id, e.row_id
                )
                SELECT source_id, COUNT(*), SUM(top1), SUM(hit5)
                FROM per_query GROUP BY source_id
                """
            ).fetchall():
                totals = source_totals[int(source_id)]
                totals["covered"] += int(source_covered)
                totals["top1"] += int(top1 or 0)
                totals["hit5"] += int(hit5 or 0)

            base_rows = con.execute(
                f"""
                SELECT q.row_id, q.hotel_cluster, c.predictions
                FROM competition_query_rows q
                JOIN geo_champion c USING (row_id)
                WHERE q.row_id >= {batch_start} AND q.row_id < {batch_stop}
                ORDER BY q.row_id
                """
            ).fetchall()
            candidate_rows = con.execute(
                """
                SELECT row_id, hotel_cluster, final_rank, confidence, booking_support
                FROM geo_candidates ORDER BY row_id, final_rank
                """
            ).fetchall()
            candidates: dict[int, list[int]] = {}
            metadata: dict[int, tuple[float, int]] = {}
            for row_id, cluster, rank, confidence, support in candidate_rows:
                row_id = int(row_id)
                candidates.setdefault(row_id, []).append(int(cluster))
                if int(rank) == 1:
                    metadata[row_id] = (float(confidence), int(support))

            size = len(base_rows)
            champion_rr = np.zeros(size, dtype=np.float32)
            geo_rr = np.zeros(size, dtype=np.float32)
            overlay_rr = np.zeros(size, dtype=np.float32)
            confidence = np.zeros(size, dtype=np.float32)
            support = np.zeros(size, dtype=np.int32)
            has_geo = np.zeros(size, dtype=bool)
            for index, (row_id, actual, champion_value) in enumerate(base_rows):
                champion = _parse_prediction(champion_value)
                geo = candidates.get(int(row_id), [])
                champion_rr[index] = _reciprocal_rank(int(actual), champion)
                if geo:
                    has_geo[index] = True
                    confidence[index], support[index] = metadata[int(row_id)]
                    geo_rr[index] = _reciprocal_rank(int(actual), geo)
                    overlay_rr[index] = _reciprocal_rank(
                        int(actual), _merge_top5(geo, champion)
                    )
                else:
                    overlay_rr[index] = champion_rr[index]

            champion_sum += float(champion_rr.sum())
            geo_sum += float(geo_rr.sum())
            covered += int(has_geo.sum())
            for threshold in thresholds:
                min_confidence, min_support = threshold
                use_geo = (
                    has_geo
                    & (confidence >= min_confidence)
                    & (support >= min_support)
                )
                score_sums[threshold] += float(
                    np.where(use_geo, overlay_rr, champion_rr).sum()
                )
                use_counts[threshold] += int(use_geo.sum())

            elapsed = time.perf_counter() - started
            print(
                f"[geo-leak] batch {number}/{len(ranges)} complete "
                f"({batch_stop - batch_start:,} rows, {elapsed / 60:.1f} min)"
            )

        best = max(thresholds, key=lambda item: score_sums[item])
        source_metrics: list[dict[str, object]] = []
        for source in SOURCES:
            totals = source_totals[source.source_id]
            source_covered = totals["covered"]
            source_metrics.append(
                {
                    "source": source.name,
                    "coverage": source_covered / validation_rows,
                    "top1_precision": (
                        totals["top1"] / source_covered if source_covered else 0.0
                    ),
                    "hit_at_5": (
                        totals["hit5"] / source_covered if source_covered else 0.0
                    ),
                }
            )
        metrics = GeoMetrics(
            cutoff=cutoff.isoformat(),
            validation_rows=validation_rows,
            distance_rows=distance_rows,
            champion_map_at_5=champion_sum / validation_rows,
            geo_map_at_5=geo_sum / validation_rows,
            overlay_map_at_5=score_sums[best] / validation_rows,
            coverage=covered / validation_rows,
            use_rate=use_counts[best] / validation_rows,
            min_confidence=best[0],
            min_booking_support=best[1],
            source_metrics=source_metrics,
        )
        output_path.write_text(
            json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        print(f"[geo-leak] metrics: {output_path}")
        return metrics
    finally:
        con.close()
