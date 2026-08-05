from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect, sql_path


@dataclass(frozen=True, slots=True)
class CandidateSource:
    source_id: int
    name: str
    keys: tuple[str, ...]
    weight: float
    top_n: int


@dataclass(frozen=True, slots=True)
class CompetitionMetrics:
    cutoff: str
    history_rows: int
    validation_rows: int
    candidate_recall_at_5: float
    candidate_recall_at_10: float
    candidate_recall_at_20: float
    map_at_5: float
    average_candidate_count: float
    source_metrics: list[dict[str, object]]


SOURCES: tuple[CandidateSource, ...] = (
    CandidateSource(
        1,
        "exact_geo_distance",
        (
            "user_location_country",
            "user_location_region",
            "user_location_city",
            "hotel_market",
            "orig_destination_distance_key",
        ),
        16.0,
        5,
    ),
    CandidateSource(
        2,
        "city_distance",
        ("user_location_city", "orig_destination_distance_key"),
        14.0,
        5,
    ),
    CandidateSource(
        3,
        "user_destination_market",
        ("user_id", "srch_destination_id", "hotel_country", "hotel_market"),
        11.0,
        5,
    ),
    CandidateSource(4, "user_destination", ("user_id", "srch_destination_id"), 8.0, 8),
    CandidateSource(5, "destination_market", ("srch_destination_id", "hotel_market"), 7.5, 10),
    CandidateSource(6, "user_market", ("user_id", "hotel_market"), 6.0, 8),
    CandidateSource(7, "destination", ("srch_destination_id",), 5.5, 12),
    CandidateSource(
        8,
        "destination_month",
        ("srch_destination_id", "checkin_month"),
        4.5,
        12,
    ),
    CandidateSource(
        9,
        "market_month",
        ("hotel_country", "hotel_market", "checkin_month"),
        3.5,
        12,
    ),
    CandidateSource(10, "country_market", ("hotel_country", "hotel_market"), 3.0, 12),
    CandidateSource(11, "user_history", ("user_id",), 2.0, 10),
    CandidateSource(12, "global", (), 0.35, 20),
)

DEFAULT_BATCH_SIZE = 25_000
DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_FETCH_SIZE = 5_000


def source_feature_names() -> tuple[str, ...]:
    names: list[str] = []
    for source in SOURCES:
        prefix = f"src_{source.source_id:02d}"
        names.extend(
            (
                f"{prefix}_score",
                f"{prefix}_share",
                f"{prefix}_rank",
                f"{prefix}_present",
            )
        )
    return tuple(names)


def _sql_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


def _create_history(con: object, train_path: Path, cutoff: date | None) -> None:
    cutoff_filter = ""
    if cutoff is not None:
        cutoff_filter = f"WHERE date_time < DATE '{cutoff.isoformat()}'"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW competition_history AS
        SELECT
            *,
            TRY_CAST(EXTRACT(month FROM srch_ci) AS SMALLINT) AS checkin_month,
            POWER(
                GREATEST(
                    1,
                    DATE_DIFF('month', DATE '2012-12-01', CAST(date_time AS DATE))
                ),
                2
            ) * (3.0 + 17.60 * is_booking) AS event_weight
        FROM read_parquet('{sql_path(train_path)}')
        {cutoff_filter}
        """
    )


def _create_period_query_rows(
    con: object,
    train_path: Path,
    *,
    start: date,
    end: date | None,
    max_queries: int | None,
) -> None:
    end_filter = "" if end is None else f"AND date_time < DATE '{end.isoformat()}'"
    limit_clause = "" if max_queries is None else f"LIMIT {max(1, max_queries)}"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE competition_query_rows AS
        WITH sampled AS (
            SELECT *
            FROM read_parquet('{sql_path(train_path)}')
            WHERE date_time >= DATE '{start.isoformat()}'
              {end_filter}
              AND is_booking = 1
            ORDER BY HASH(
                date_time, user_id, srch_destination_id, hotel_market, hotel_cluster
            )
            {limit_clause}
        )
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY date_time, user_id, srch_destination_id, hotel_market, hotel_cluster
            ) - 1 AS row_id,
            *,
            TRY_CAST(EXTRACT(month FROM srch_ci) AS SMALLINT) AS checkin_month
        FROM sampled
        """
    )


def _create_validation_rows(con: object, train_path: Path, cutoff: date) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE competition_query_rows AS
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY date_time, user_id, srch_destination_id, hotel_market, hotel_cluster
            ) - 1 AS row_id,
            *,
            TRY_CAST(EXTRACT(month FROM srch_ci) AS SMALLINT) AS checkin_month
        FROM read_parquet('{sql_path(train_path)}')
        WHERE date_time >= DATE '{cutoff.isoformat()}'
          AND is_booking = 1
        """
    )


def _create_test_rows(con: object, test_path: Path) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE competition_query_rows AS
        SELECT
            id AS row_id,
            *,
            TRY_CAST(EXTRACT(month FROM srch_ci) AS SMALLINT) AS checkin_month
        FROM read_parquet('{sql_path(test_path)}')
        """
    )


def _lookup_sql(source: CandidateSource) -> str:
    table_name = f"competition_top_{_sql_identifier(source.name)}"
    key_list = ", ".join(_sql_identifier(key) for key in source.keys)
    partition = key_list if key_list else "hotel_cluster * 0"
    select_keys = f"{key_list}," if key_list else ""
    group_keys = f"{key_list}, hotel_cluster" if key_list else "hotel_cluster"
    non_null_filter = " AND ".join(f"{key} IS NOT NULL" for key in source.keys)
    where_clause = f"WHERE {non_null_filter}" if non_null_filter else ""
    return f"""
    CREATE OR REPLACE TEMP TABLE {table_name} AS
    WITH scores AS (
        SELECT
            {select_keys}
            hotel_cluster,
            SUM(event_weight) AS raw_score
        FROM competition_history
        {where_clause}
        GROUP BY {group_keys}
    ),
    ranked AS (
        SELECT
            *,
            raw_score / NULLIF(
                SUM(raw_score) OVER (PARTITION BY {partition}),
                0.0
            ) AS score_share,
            ROW_NUMBER() OVER (
                PARTITION BY {partition}
                ORDER BY raw_score DESC, hotel_cluster
            ) AS source_rank
        FROM scores
    )
    SELECT *
    FROM ranked
    WHERE source_rank <= {source.top_n}
    """


def _candidate_relation(source: CandidateSource) -> str:
    table_name = f"competition_top_{_sql_identifier(source.name)}"
    if not source.keys:
        return f"CROSS JOIN {table_name} t"
    conditions = " AND ".join(f"q.{key} = t.{key}" for key in source.keys)
    return f"JOIN {table_name} t ON {conditions}"


def _candidate_select_sql(
    source: CandidateSource,
    *,
    row_id_start: int,
    row_id_end: int,
) -> str:
    return f"""
    SELECT
        q.row_id,
        t.hotel_cluster,
        {source.source_id}::TINYINT AS source_id,
        t.source_rank::SMALLINT AS source_rank,
        t.score_share::FLOAT AS score_share,
        {source.weight} * (
            0.82 * t.score_share + 0.18 / t.source_rank
        ) AS weighted_score
    FROM competition_query_rows q
    {_candidate_relation(source)}
    WHERE q.row_id >= {row_id_start}
      AND q.row_id < {row_id_end}
    """


def _build_lookup_tables(con: object) -> None:
    print("[competition] building lookup tables")
    for source in SOURCES:
        print(f"[competition] source: {source.name}")
        con.execute(_lookup_sql(source))


def _row_bounds(con: object) -> tuple[int, int, int]:
    minimum, maximum, count = con.execute(
        "SELECT MIN(row_id), MAX(row_id), COUNT(*) FROM competition_query_rows"
    ).fetchone()
    if int(count) == 0:
        return 0, 0, 0
    return int(minimum), int(maximum) + 1, int(count)


def _batch_ranges(start: int, stop: int, batch_size: int) -> Iterator[tuple[int, int]]:
    for row_id_start in range(start, stop, batch_size):
        yield row_id_start, min(row_id_start + batch_size, stop)


def _create_candidate_batch(
    con: object,
    *,
    row_id_start: int,
    row_id_end: int,
    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
) -> None:
    union_sql = "\nUNION ALL\n".join(
        _candidate_select_sql(
            source,
            row_id_start=row_id_start,
            row_id_end=row_id_end,
        )
        for source in SOURCES
    )
    source_columns: list[str] = []
    for source in SOURCES:
        prefix = f"src_{source.source_id:02d}"
        source_columns.extend(
            [
                (
                    "COALESCE(MAX(weighted_score) FILTER "
                    f"(WHERE source_id = {source.source_id}), 0.0)::FLOAT "
                    f"AS {prefix}_score"
                ),
                (
                    "COALESCE(MAX(score_share) FILTER "
                    f"(WHERE source_id = {source.source_id}), 0.0)::FLOAT "
                    f"AS {prefix}_share"
                ),
                (
                    "COALESCE(MIN(source_rank) FILTER "
                    f"(WHERE source_id = {source.source_id}), 0)::SMALLINT "
                    f"AS {prefix}_rank"
                ),
                (
                    "MAX(CASE "
                    f"WHEN source_id = {source.source_id} THEN 1 ELSE 0 END)::TINYINT "
                    f"AS {prefix}_present"
                ),
            ]
        )
    source_feature_sql = ",\n                ".join(source_columns)
    con.execute("DROP TABLE IF EXISTS competition_batch_candidates")
    con.execute(
        f"""
        CREATE TEMP TABLE competition_batch_candidates AS
        WITH candidate_events AS (
            {union_sql}
        ),
        scored AS (
            SELECT
                row_id,
                hotel_cluster,
                SUM(weighted_score)::FLOAT AS combined_score,
                COUNT(*)::SMALLINT AS source_count,
                MAX(weighted_score)::FLOAT AS strongest_source_score,
                MIN(source_rank)::SMALLINT AS best_source_rank,
                FIRST(source_id ORDER BY weighted_score DESC, source_id)::TINYINT
                    AS strongest_source_id,
                {source_feature_sql}
            FROM candidate_events
            GROUP BY row_id, hotel_cluster
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY row_id
                    ORDER BY
                        combined_score DESC,
                        source_count DESC,
                        strongest_source_score DESC,
                        hotel_cluster
                ) AS final_rank
            FROM scored
        )
        SELECT *
        FROM ranked
        WHERE final_rank <= {candidate_pool_size}
        """
    )


def _stream_query_to_csv(
    con: object,
    query: str,
    writer: csv.writer,
    *,
    fetch_size: int = DEFAULT_FETCH_SIZE,
) -> None:
    cursor = con.execute(query)
    while True:
        rows = cursor.fetchmany(fetch_size)
        if not rows:
            return
        writer.writerows(rows)


def _source_diagnostics(con: object, validation_rows: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source in SOURCES:
        table_name = f"competition_top_{_sql_identifier(source.name)}"
        if source.keys:
            conditions = " AND ".join(f"q.{key} = t.{key}" for key in source.keys)
            covered, hits = con.execute(
                f"""
                SELECT
                    SUM(CASE WHEN EXISTS (
                        SELECT 1 FROM {table_name} t WHERE {conditions}
                    ) THEN 1 ELSE 0 END),
                    SUM(CASE WHEN EXISTS (
                        SELECT 1
                        FROM {table_name} t
                        WHERE {conditions}
                          AND t.hotel_cluster = q.hotel_cluster
                    ) THEN 1 ELSE 0 END)
                FROM competition_query_rows q
                """
            ).fetchone()
        else:
            covered, hits = con.execute(
                f"""
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN q.hotel_cluster IN (
                        SELECT hotel_cluster FROM {table_name}
                    ) THEN 1 ELSE 0 END)
                FROM competition_query_rows q
                """
            ).fetchone()
        result.append(
            {
                "source_id": source.source_id,
                "source": source.name,
                "weight": source.weight,
                "top_n": source.top_n,
                "coverage": int(covered or 0) / validation_rows,
                "standalone_recall": int(hits or 0) / validation_rows,
            }
        )
    return result


def validate_competition_candidates(
    paths: ProjectPaths,
    *,
    cutoff: date = date(2014, 8, 1),
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> CompetitionMetrics:
    train_path = paths.processed_dir / "train.parquet"
    if not train_path.exists():
        raise FileNotFoundError("train.parquet is missing. Run prepare first.")
    paths.ensure_directories()
    predictions_path = paths.artifacts_dir / "competition_candidate_predictions.csv"
    metrics_path = paths.artifacts_dir / "competition_candidate_metrics.json"
    con = connect(
        paths.processed_dir / "competition.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )
    try:
        _create_history(con, train_path, cutoff)
        _create_validation_rows(con, train_path, cutoff)
        _build_lookup_tables(con)
        history_rows = int(
            con.execute("SELECT COUNT(*) FROM competition_history").fetchone()[0]
        )
        start, stop, validation_rows = _row_bounds(con)
        if validation_rows == 0:
            raise RuntimeError("The temporal validation split contains no booking rows.")
        source_metrics = _source_diagnostics(con, validation_rows)
        ranges = list(_batch_ranges(start, stop, batch_size))
        hit_at_5 = 0
        hit_at_10 = 0
        hit_at_20 = 0
        reciprocal_rank_sum = 0.0
        candidate_count_sum = 0
        predictions_path.unlink(missing_ok=True)
        started_at = time.perf_counter()
        print(
            "[competition] validating and exporting in "
            f"{len(ranges)} batches of up to {batch_size:,} rows"
        )
        with predictions_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(
                ["row_id", "actual_hotel_cluster", "candidate_hotel_clusters"]
            )
            for batch_number, (row_id_start, row_id_end) in enumerate(ranges, start=1):
                _create_candidate_batch(
                    con,
                    row_id_start=row_id_start,
                    row_id_end=row_id_end,
                )
                values = con.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN f.final_rank <= 5 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN f.final_rank <= 10 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN f.final_rank <= 20 THEN 1 ELSE 0 END),
                        SUM(CASE
                            WHEN f.final_rank <= 5 THEN 1.0 / f.final_rank
                            ELSE 0.0
                        END)
                    FROM competition_query_rows q
                    LEFT JOIN competition_batch_candidates f
                      ON q.row_id = f.row_id
                     AND q.hotel_cluster = f.hotel_cluster
                    WHERE q.row_id >= {row_id_start}
                      AND q.row_id < {row_id_end}
                    """
                ).fetchone()
                hit_at_5 += int(values[0] or 0)
                hit_at_10 += int(values[1] or 0)
                hit_at_20 += int(values[2] or 0)
                reciprocal_rank_sum += float(values[3] or 0.0)
                candidate_count_sum += int(
                    con.execute(
                        "SELECT COUNT(*) FROM competition_batch_candidates"
                    ).fetchone()[0]
                )
                _stream_query_to_csv(
                    con,
                    f"""
                    SELECT
                        q.row_id,
                        q.hotel_cluster,
                        STRING_AGG(
                            CAST(f.hotel_cluster AS VARCHAR),
                            ' ' ORDER BY f.final_rank
                        )
                    FROM competition_query_rows q
                    LEFT JOIN competition_batch_candidates f USING (row_id)
                    WHERE q.row_id >= {row_id_start}
                      AND q.row_id < {row_id_end}
                    GROUP BY q.row_id, q.hotel_cluster
                    ORDER BY q.row_id
                    """,
                    writer,
                )
                elapsed = time.perf_counter() - started_at
                completed = batch_number / len(ranges)
                remaining = elapsed * (1.0 - completed) / completed
                print(
                    f"[competition] batch {batch_number}/{len(ranges)} complete "
                    f"({row_id_end - row_id_start:,} rows, "
                    f"elapsed {elapsed / 60:.1f} min, ETA {remaining / 60:.1f} min)"
                )
        metrics = CompetitionMetrics(
            cutoff=cutoff.isoformat(),
            history_rows=history_rows,
            validation_rows=validation_rows,
            candidate_recall_at_5=hit_at_5 / validation_rows,
            candidate_recall_at_10=hit_at_10 / validation_rows,
            candidate_recall_at_20=hit_at_20 / validation_rows,
            map_at_5=reciprocal_rank_sum / validation_rows,
            average_candidate_count=candidate_count_sum / validation_rows,
            source_metrics=source_metrics,
        )
        metrics_path.write_text(
            json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        print(f"[competition] predictions: {predictions_path}")
        print(f"[competition] metrics: {metrics_path}")
        return metrics
    finally:
        con.close()


def build_competition_submission(
    paths: ProjectPaths,
    *,
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Path:
    train_path = paths.processed_dir / "train.parquet"
    test_path = paths.processed_dir / "test.parquet"
    if not train_path.exists() or not test_path.exists():
        raise FileNotFoundError("Processed train/test files are missing. Run prepare first.")
    paths.ensure_directories()
    submission_path = paths.artifacts_dir / "submission_competition_heuristic.csv"
    con = connect(
        paths.processed_dir / "competition.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )
    try:
        _create_history(con, train_path, cutoff=None)
        _create_test_rows(con, test_path)
        _build_lookup_tables(con)
        start, stop, test_rows = _row_bounds(con)
        if test_rows == 0:
            raise RuntimeError("The test dataset contains no rows.")
        ranges = list(_batch_ranges(start, stop, batch_size))
        submission_path.unlink(missing_ok=True)
        started_at = time.perf_counter()
        with submission_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(["id", "hotel_cluster"])
            for batch_number, (row_id_start, row_id_end) in enumerate(ranges, start=1):
                _create_candidate_batch(
                    con,
                    row_id_start=row_id_start,
                    row_id_end=row_id_end,
                )
                _stream_query_to_csv(
                    con,
                    f"""
                    SELECT
                        q.row_id,
                        STRING_AGG(
                            CAST(f.hotel_cluster AS VARCHAR),
                            ' ' ORDER BY f.final_rank
                        ) FILTER (WHERE f.final_rank <= 5)
                    FROM competition_query_rows q
                    JOIN competition_batch_candidates f USING (row_id)
                    WHERE q.row_id >= {row_id_start}
                      AND q.row_id < {row_id_end}
                    GROUP BY q.row_id
                    ORDER BY q.row_id
                    """,
                    writer,
                )
                elapsed = time.perf_counter() - started_at
                completed = batch_number / len(ranges)
                remaining = elapsed * (1.0 - completed) / completed
                print(
                    f"[competition] batch {batch_number}/{len(ranges)} complete "
                    f"({row_id_end - row_id_start:,} rows, "
                    f"elapsed {elapsed / 60:.1f} min, ETA {remaining / 60:.1f} min)"
                )
        print(f"[competition] submission: {submission_path}")
        return submission_path
    finally:
        con.close()
