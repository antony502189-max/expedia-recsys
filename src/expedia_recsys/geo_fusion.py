from __future__ import annotations

import json
import time
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
from expedia_recsys.duck import connect
from expedia_recsys.geo_leak import (
    _build_lookups,
    _create_batch,
    _load_champion,
    _parse_prediction,
    _reciprocal_rank,
)

if TYPE_CHECKING:
    import duckdb


@dataclass(frozen=True, slots=True)
class FusionAction:
    name: str
    geo_count: int
    insert_after: int


@dataclass(frozen=True, slots=True)
class FusionPolicy:
    action: str
    source_mode: str
    min_confidence: float
    min_booking_support: int
    min_source_agreement: int


@dataclass(frozen=True, slots=True)
class FusionMetrics:
    cutoff: str
    validation_rows: int
    calibration_rows: int
    evaluation_rows: int
    champion_map_at_5: float
    calibration_champion_map_at_5: float
    calibration_fusion_map_at_5: float
    evaluation_champion_map_at_5: float
    evaluation_fusion_map_at_5: float
    full_fusion_map_at_5: float
    full_delta_map_at_5: float
    use_rate: float
    calibration_use_rate: float
    evaluation_use_rate: float
    policy: dict[str, object]


ACTIONS: tuple[FusionAction, ...] = (
    FusionAction("top1_front", geo_count=1, insert_after=0),
    FusionAction("top1_after_rank1", geo_count=1, insert_after=1),
    FusionAction("top1_after_rank2", geo_count=1, insert_after=2),
    FusionAction("top2_front", geo_count=2, insert_after=0),
    FusionAction("top3_front", geo_count=3, insert_after=0),
    FusionAction("full_front", geo_count=5, insert_after=0),
)
SOURCE_MODES: tuple[str, ...] = ("all", "exact_only", "precise")
CONFIDENCE_GRID: tuple[float, ...] = (0.90, 0.95, 0.975, 0.99)
SUPPORT_GRID: tuple[int, ...] = (5, 10, 20, 50)
AGREEMENT_GRID: tuple[int, ...] = (1, 2)


def _merge_at(
    champion: list[int],
    geo: list[int],
    *,
    geo_count: int,
    insert_after: int,
) -> list[int]:
    result: list[int] = []
    ordered = (
        champion[:insert_after]
        + geo[:geo_count]
        + champion[insert_after:]
    )
    for cluster in ordered:
        value = int(cluster)
        if 0 <= value <= 99 and value not in result:
            result.append(value)
        if len(result) == 5:
            break
    return result


def _policy_grid() -> tuple[FusionPolicy, ...]:
    result: list[FusionPolicy] = []
    for action in ACTIONS:
        for source_mode in SOURCE_MODES:
            for confidence in CONFIDENCE_GRID:
                for support in SUPPORT_GRID:
                    for agreement in AGREEMENT_GRID:
                        result.append(
                            FusionPolicy(
                                action=action.name,
                                source_mode=source_mode,
                                min_confidence=confidence,
                                min_booking_support=support,
                                min_source_agreement=agreement,
                            )
                        )
    return tuple(result)


def _source_gate(source_ids: np.ndarray, mode: str) -> np.ndarray:
    if mode == "all":
        return np.ones(len(source_ids), dtype=bool)
    if mode == "exact_only":
        return source_ids == 1
    if mode == "precise":
        return np.isin(source_ids, np.asarray((1, 2, 3, 6), dtype=np.int16))
    raise ValueError(f"Unsupported source mode: {mode}")


def _candidate_rows(
    con: duckdb.DuckDBPyConnection,
) -> list[tuple[object, ...]]:
    return con.execute(
        """
        WITH agreement AS (
            SELECT
                row_id,
                hotel_cluster,
                COUNT(DISTINCT source_id)::SMALLINT AS source_agreement
            FROM geo_events
            GROUP BY row_id, hotel_cluster
        )
        SELECT
            c.row_id,
            c.hotel_cluster,
            c.final_rank,
            c.confidence,
            c.booking_support,
            c.source_id,
            a.source_agreement
        FROM geo_candidates c
        JOIN agreement a USING (row_id, hotel_cluster)
        ORDER BY c.row_id, c.final_rank
        """
    ).fetchall()


def validate_geo_fusion(
    paths: ProjectPaths,
    *,
    cutoff: date = date(2014, 8, 1),
    champion_path: Path | None = None,
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> FusionMetrics:
    train_path = paths.processed_dir / "train.parquet"
    if not train_path.exists():
        raise FileNotFoundError("train.parquet is missing. Run prepare first.")

    paths.ensure_directories()
    champion_path = champion_path or (
        paths.artifacts_dir / "ranker_validation_predictions.csv"
    )
    output_path = paths.artifacts_dir / "geo_fusion_validation_metrics.json"
    con = connect(
        paths.processed_dir / "geo_fusion_validation.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )

    policies = _policy_grid()
    action_by_name = {action.name: action for action in ACTIONS}
    calibration_sums = {policy: 0.0 for policy in policies}
    evaluation_sums = {policy: 0.0 for policy in policies}
    calibration_uses = {policy: 0 for policy in policies}
    evaluation_uses = {policy: 0 for policy in policies}
    calibration_champion_sum = 0.0
    evaluation_champion_sum = 0.0
    calibration_rows = 0
    evaluation_rows = 0

    try:
        _create_history(con, train_path, cutoff)
        _create_validation_rows(con, train_path, cutoff)
        _build_lookups(con)
        start, stop, validation_rows = _row_bounds(con)
        _load_champion(con, champion_path, validation_rows)

        ranges = list(_batch_ranges(start, stop, batch_size))
        started = time.perf_counter()
        for number, (batch_start, batch_stop) in enumerate(ranges, start=1):
            _create_batch(con, batch_start, batch_stop)
            base_rows = con.execute(
                f"""
                SELECT q.row_id, q.hotel_cluster, c.predictions
                FROM competition_query_rows q
                JOIN geo_champion c USING (row_id)
                WHERE q.row_id >= {batch_start} AND q.row_id < {batch_stop}
                ORDER BY q.row_id
                """
            ).fetchall()

            candidates: dict[int, list[int]] = {}
            metadata: dict[int, tuple[float, int, int, int]] = {}
            for (
                row_id,
                cluster,
                rank,
                confidence,
                support,
                source_id,
                agreement,
            ) in _candidate_rows(con):
                row = int(row_id)
                candidates.setdefault(row, []).append(int(cluster))
                if int(rank) == 1:
                    metadata[row] = (
                        float(confidence),
                        int(support),
                        int(source_id),
                        int(agreement),
                    )

            size = len(base_rows)
            row_ids = np.empty(size, dtype=np.int64)
            champion_rr = np.zeros(size, dtype=np.float32)
            confidence = np.zeros(size, dtype=np.float32)
            support = np.zeros(size, dtype=np.int32)
            source_id = np.zeros(size, dtype=np.int16)
            agreement = np.zeros(size, dtype=np.int16)
            has_geo = np.zeros(size, dtype=bool)
            action_rr = {
                action.name: np.zeros(size, dtype=np.float32) for action in ACTIONS
            }

            for index, (row_id, actual, champion_value) in enumerate(base_rows):
                row = int(row_id)
                row_ids[index] = row
                champion = _parse_prediction(champion_value)
                geo = candidates.get(row, [])
                champion_rr[index] = _reciprocal_rank(int(actual), champion)
                if not geo:
                    for values in action_rr.values():
                        values[index] = champion_rr[index]
                    continue

                has_geo[index] = True
                (
                    confidence[index],
                    support[index],
                    source_id[index],
                    agreement[index],
                ) = metadata[row]
                for action in ACTIONS:
                    merged = _merge_at(
                        champion,
                        geo,
                        geo_count=action.geo_count,
                        insert_after=action.insert_after,
                    )
                    action_rr[action.name][index] = _reciprocal_rank(
                        int(actual), merged
                    )

            calibration_mask = (row_ids & 1) == 0
            evaluation_mask = ~calibration_mask
            calibration_rows += int(calibration_mask.sum())
            evaluation_rows += int(evaluation_mask.sum())
            calibration_champion_sum += float(champion_rr[calibration_mask].sum())
            evaluation_champion_sum += float(champion_rr[evaluation_mask].sum())

            source_gates = {
                mode: _source_gate(source_id, mode) for mode in SOURCE_MODES
            }
            for policy in policies:
                gate = (
                    has_geo
                    & source_gates[policy.source_mode]
                    & (confidence >= policy.min_confidence)
                    & (support >= policy.min_booking_support)
                    & (agreement >= policy.min_source_agreement)
                )
                values = action_rr[policy.action]
                calibration_use = gate & calibration_mask
                evaluation_use = gate & evaluation_mask
                calibration_sums[policy] += float(
                    np.where(calibration_use, values, champion_rr)[
                        calibration_mask
                    ].sum()
                )
                evaluation_sums[policy] += float(
                    np.where(evaluation_use, values, champion_rr)[
                        evaluation_mask
                    ].sum()
                )
                calibration_uses[policy] += int(calibration_use.sum())
                evaluation_uses[policy] += int(evaluation_use.sum())

            elapsed = time.perf_counter() - started
            print(
                f"[geo-fusion] batch {number}/{len(ranges)} complete "
                f"({batch_stop - batch_start:,} rows, {elapsed / 60:.1f} min)"
            )

        if calibration_rows == 0 or evaluation_rows == 0:
            raise RuntimeError("Could not create calibration/evaluation row split.")

        best = max(
            policies,
            key=lambda policy: (
                calibration_sums[policy] / calibration_rows,
                -calibration_uses[policy],
                policy.action,
            ),
        )
        champion_sum = calibration_champion_sum + evaluation_champion_sum
        fusion_sum = calibration_sums[best] + evaluation_sums[best]
        total_uses = calibration_uses[best] + evaluation_uses[best]

        metrics = FusionMetrics(
            cutoff=cutoff.isoformat(),
            validation_rows=validation_rows,
            calibration_rows=calibration_rows,
            evaluation_rows=evaluation_rows,
            champion_map_at_5=champion_sum / validation_rows,
            calibration_champion_map_at_5=(
                calibration_champion_sum / calibration_rows
            ),
            calibration_fusion_map_at_5=calibration_sums[best] / calibration_rows,
            evaluation_champion_map_at_5=(
                evaluation_champion_sum / evaluation_rows
            ),
            evaluation_fusion_map_at_5=evaluation_sums[best] / evaluation_rows,
            full_fusion_map_at_5=fusion_sum / validation_rows,
            full_delta_map_at_5=(fusion_sum - champion_sum) / validation_rows,
            use_rate=total_uses / validation_rows,
            calibration_use_rate=calibration_uses[best] / calibration_rows,
            evaluation_use_rate=evaluation_uses[best] / evaluation_rows,
            policy=asdict(best),
        )
        output_path.write_text(
            json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        print(f"[geo-fusion] metrics: {output_path}")
        return metrics
    finally:
        con.close()
