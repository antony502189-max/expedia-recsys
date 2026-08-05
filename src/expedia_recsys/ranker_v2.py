from __future__ import annotations

import csv
import inspect
import json
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from expedia_recsys.competition import (
    DEFAULT_BATCH_SIZE,
    _batch_ranges,
    _build_lookup_tables,
    _create_candidate_batch,
    _create_history,
    _create_test_rows,
    _create_validation_rows,
    _row_bounds,
)
from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect
from expedia_recsys.ranker import (
    CATEGORICAL_FEATURES,
    RANKER_FEATURES,
    _feature_select_sql,
    _filter_trainable_groups,
    _load_training_frame,
    _optimize_frame,
    _write_feature_importance,
)

if TYPE_CHECKING:
    import lightgbm as lgb


LEGACY_SOURCE_ORDER: tuple[int, ...] = (1, 2, 3, 5, 10, 12)
WEIGHT_STEP = 0.1


@dataclass(frozen=True, slots=True)
class BlendWeights:
    model: float
    heuristic: float
    legacy: float


@dataclass(frozen=True, slots=True)
class RankerMetrics:
    train_history_cutoff: str
    train_query_start: str
    train_query_end: str
    validation_cutoff: str
    train_queries_requested: int
    train_queries_used: int
    train_rows: int
    validation_rows: int
    candidate_recall_at_20: float
    model_map_at_5: float
    heuristic_map_at_5: float
    legacy_map_at_5: float
    map_at_5: float
    best_iteration: int
    model_weight: float
    heuristic_weight: float
    legacy_weight: float
    calibration_map_at_5: float
    model_path: str


def _new_ranker(*, threads: int, n_estimators: int = 1_500) -> lgb.LGBMRanker:
    import lightgbm as lgb

    return lgb.LGBMRanker(
        objective="lambdarank",
        metric="map",
        boosting_type="gbdt",
        n_estimators=n_estimators,
        learning_rate=0.025,
        num_leaves=63,
        max_depth=-1,
        min_child_samples=80,
        max_bin=127,
        subsample=0.9,
        subsample_freq=1,
        colsample_bytree=0.9,
        reg_alpha=0.1,
        reg_lambda=1.5,
        random_state=2026,
        n_jobs=threads,
        force_col_wise=True,
        lambdarank_truncation_level=10,
        label_gain=[0, 1],
        verbosity=-1,
    )


def _split_eval_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    row_ids = frame["row_id"].drop_duplicates().to_numpy(dtype=np.int64)
    if len(row_ids) < 2:
        raise RuntimeError("At least two evaluation queries are required.")
    stopping_ids = set(row_ids[::2].tolist())
    stopping = frame.loc[frame["row_id"].isin(stopping_ids)].copy()
    calibration = frame.loc[~frame["row_id"].isin(stopping_ids)].copy()
    if stopping.empty or calibration.empty:
        raise RuntimeError("Could not split evaluation queries.")
    return stopping, calibration


def _fit_ranker(
    train_frame: pd.DataFrame,
    stopping_frame: pd.DataFrame,
    *,
    threads: int,
) -> tuple[lgb.LGBMRanker, int, int]:
    import lightgbm as lgb

    train_frame, train_group = _filter_trainable_groups(train_frame)
    stopping_frame, stopping_group = _filter_trainable_groups(stopping_frame)
    model = _new_ranker(threads=threads)
    fit_kwargs: dict[str, object] = {
        "group": train_group,
        "eval_group": [stopping_group],
        "eval_metric": "map",
        "eval_at": [5],
        "categorical_feature": list(CATEGORICAL_FEATURES),
        "callbacks": [
            lgb.early_stopping(100, first_metric_only=True, verbose=True),
            lgb.log_evaluation(25),
        ],
    }
    eval_x = stopping_frame.loc[:, RANKER_FEATURES]
    eval_y = stopping_frame["label"]
    if "eval_X" in inspect.signature(model.fit).parameters:
        fit_kwargs["eval_X"] = (eval_x,)
        fit_kwargs["eval_y"] = (eval_y,)
    else:
        fit_kwargs["eval_set"] = [(eval_x, eval_y)]
    model.fit(
        train_frame.loc[:, RANKER_FEATURES],
        train_frame["label"],
        **fit_kwargs,
    )
    return model, len(train_group), len(train_frame)


def _legacy_rank(frame: pd.DataFrame) -> pd.Series:
    priority = np.full(len(frame), 99, dtype=np.int16)
    source_rank = np.full(len(frame), 999, dtype=np.int16)
    for source_priority, source_id in enumerate(LEGACY_SOURCE_ORDER, start=1):
        present = frame[f"src_{source_id:02d}_present"].to_numpy(dtype=np.int8)
        rank = frame[f"src_{source_id:02d}_rank"].to_numpy(dtype=np.int16)
        mask = (priority == 99) & (present == 1)
        priority[mask] = source_priority
        source_rank[mask] = rank[mask]

    ordered = pd.DataFrame(
        {
            "_index": np.arange(len(frame), dtype=np.int64),
            "row_id": frame["row_id"].to_numpy(dtype=np.int64),
            "priority": priority,
            "source_rank": source_rank,
            "combined_score": frame["combined_score"].to_numpy(dtype=np.float32),
            "candidate_cluster": frame["candidate_cluster"].to_numpy(dtype=np.int16),
        }
    )
    ordered.sort_values(
        [
            "row_id",
            "priority",
            "source_rank",
            "combined_score",
            "candidate_cluster",
        ],
        ascending=[True, True, True, False, True],
        inplace=True,
        kind="mergesort",
    )
    ordered["legacy_rank"] = ordered.groupby("row_id", sort=False).cumcount() + 1
    ordered.sort_values("_index", inplace=True)
    return ordered["legacy_rank"].astype("int16").reset_index(drop=True)


def _component_frame(
    model: lgb.Booster,
    frame: pd.DataFrame,
    best_iteration: int,
) -> pd.DataFrame:
    prediction = model.predict(
        frame.loc[:, RANKER_FEATURES],
        num_iteration=best_iteration if best_iteration > 0 else None,
    )
    columns = [
        "row_id",
        "candidate_cluster",
        "heuristic_rank",
        "combined_score",
    ]
    if "label" in frame:
        columns.append("label")
    ranked = frame.loc[:, columns].copy().reset_index(drop=True)
    ranked["prediction"] = np.asarray(prediction, dtype=np.float32)
    ranked["legacy_rank"] = _legacy_rank(frame).to_numpy(dtype=np.int16)

    model_order = ranked.sort_values(
        ["row_id", "prediction", "combined_score", "candidate_cluster"],
        ascending=[True, False, False, True],
        kind="mergesort",
    ).copy()
    model_order["model_rank"] = model_order.groupby("row_id", sort=False).cumcount() + 1
    model_rank = model_order.sort_index()["model_rank"].to_numpy(dtype=np.int16)
    ranked["model_rank"] = model_rank
    ranked["model_component"] = 1.0 / ranked["model_rank"].to_numpy(dtype=np.float32)
    ranked["heuristic_component"] = (
        1.0 / ranked["heuristic_rank"].to_numpy(dtype=np.float32)
    )
    ranked["legacy_component"] = 1.0 / ranked["legacy_rank"].to_numpy(dtype=np.float32)
    return ranked


def _rank_components(
    components: pd.DataFrame,
    weights: BlendWeights,
) -> pd.DataFrame:
    ranked = components.copy()
    ranked["blend_score"] = (
        weights.model * ranked["model_component"]
        + weights.heuristic * ranked["heuristic_component"]
        + weights.legacy * ranked["legacy_component"]
    )
    ranked.sort_values(
        [
            "row_id",
            "blend_score",
            "prediction",
            "combined_score",
            "candidate_cluster",
        ],
        ascending=[True, False, False, False, True],
        inplace=True,
        kind="mergesort",
    )
    ranked["blend_rank"] = ranked.groupby("row_id", sort=False).cumcount() + 1
    return ranked


def _map_at_5(ranked: pd.DataFrame, rank_column: str, query_count: int) -> float:
    if query_count <= 0:
        raise ValueError("query_count must be positive")
    positives = ranked.loc[ranked["label"].eq(1)]
    top5 = positives.loc[positives[rank_column].le(5), rank_column]
    return float((1.0 / top5).sum()) / query_count


def _candidate_recall(ranked: pd.DataFrame, query_count: int) -> float:
    if query_count <= 0:
        raise ValueError("query_count must be positive")
    return float(ranked.loc[ranked["label"].eq(1), "row_id"].nunique()) / query_count


def _weight_grid(step: float = WEIGHT_STEP) -> tuple[BlendWeights, ...]:
    units = int(round(1.0 / step))
    result: list[BlendWeights] = []
    for model_units in range(units + 1):
        for heuristic_units in range(units - model_units + 1):
            legacy_units = units - model_units - heuristic_units
            result.append(
                BlendWeights(
                    model=model_units / units,
                    heuristic=heuristic_units / units,
                    legacy=legacy_units / units,
                )
            )
    return tuple(result)


def _tune_blend(
    model: lgb.Booster,
    calibration_frame: pd.DataFrame,
    best_iteration: int,
) -> tuple[BlendWeights, dict[str, float]]:
    components = _component_frame(model, calibration_frame, best_iteration)
    query_count = int(components["row_id"].nunique())
    diagnostics = {
        "model": _map_at_5(components, "model_rank", query_count),
        "heuristic": _map_at_5(components, "heuristic_rank", query_count),
        "legacy": _map_at_5(components, "legacy_rank", query_count),
    }
    best_weights = BlendWeights(model=0.0, heuristic=1.0, legacy=0.0)
    best_score = -1.0
    for weights in _weight_grid():
        ranked = _rank_components(components, weights)
        score = _map_at_5(ranked, "blend_rank", query_count)
        candidate = (
            score,
            -weights.model,
            weights.legacy,
            weights.heuristic,
        )
        incumbent = (
            best_score,
            -best_weights.model,
            best_weights.legacy,
            best_weights.heuristic,
        )
        if candidate > incumbent:
            best_score = score
            best_weights = weights
    diagnostics["blend"] = best_score
    diagnostics["queries"] = float(query_count)
    print(
        "[ranker] calibration MAP@5: "
        f"model={diagnostics['model']:.6f}, "
        f"heuristic={diagnostics['heuristic']:.6f}, "
        f"legacy={diagnostics['legacy']:.6f}, "
        f"blend={best_score:.6f}; "
        f"weights=({best_weights.model:.1f}, "
        f"{best_weights.heuristic:.1f}, {best_weights.legacy:.1f})"
    )
    return best_weights, diagnostics


def _score_full_validation(
    paths: ProjectPaths,
    *,
    model_path: Path,
    best_iteration: int,
    weights: BlendWeights,
    cutoff: date,
    threads: int,
    memory_limit: str,
    batch_size: int,
) -> tuple[int, float, dict[str, float]]:
    import lightgbm as lgb

    train_path = paths.processed_dir / "train.parquet"
    predictions_path = paths.artifacts_dir / "ranker_validation_predictions.csv"
    model = lgb.Booster(model_file=str(model_path))
    con = connect(
        paths.processed_dir / "ranker_validation.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )
    try:
        _create_history(con, train_path, cutoff)
        _create_validation_rows(con, train_path, cutoff)
        _build_lookup_tables(con)
        start, stop, validation_rows = _row_bounds(con)
        ranges = list(_batch_ranges(start, stop, batch_size))
        positive_candidates = 0
        reciprocal_sums = {
            "model": 0.0,
            "heuristic": 0.0,
            "legacy": 0.0,
            "blend": 0.0,
        }
        predictions_path.unlink(missing_ok=True)
        started_at = time.perf_counter()
        with predictions_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(["row_id", "actual_hotel_cluster", "hotel_cluster"])
            for batch_number, (row_id_start, row_id_end) in enumerate(ranges, start=1):
                _create_candidate_batch(
                    con,
                    row_id_start=row_id_start,
                    row_id_end=row_id_end,
                )
                frame = con.execute(
                    _feature_select_sql(row_id_start, row_id_end, include_label=True)
                ).fetch_df()
                frame = _optimize_frame(frame, include_label=True)
                components = _component_frame(model, frame, best_iteration)
                ranked = _rank_components(components, weights)
                positives = ranked.loc[ranked["label"].eq(1)]
                positive_candidates += len(positives)
                for name, rank_column in (
                    ("model", "model_rank"),
                    ("heuristic", "heuristic_rank"),
                    ("legacy", "legacy_rank"),
                    ("blend", "blend_rank"),
                ):
                    top5 = positives.loc[positives[rank_column].le(5), rank_column]
                    reciprocal_sums[name] += float((1.0 / top5).sum())

                actual = frame.loc[
                    :, ["row_id", "actual_hotel_cluster"]
                ].drop_duplicates("row_id")
                top5 = ranked.loc[ranked["blend_rank"].le(5)]
                predicted = top5.groupby("row_id", sort=False)["candidate_cluster"].agg(
                    lambda values: " ".join(str(int(value)) for value in values)
                )
                batch_rows = pd.DataFrame(
                    {"row_id": np.arange(row_id_start, row_id_end, dtype=np.int64)}
                ).merge(actual, on="row_id", how="left")
                batch_rows = batch_rows.merge(
                    predicted.rename("hotel_cluster"),
                    on="row_id",
                    how="left",
                )
                writer.writerows(batch_rows.itertuples(index=False, name=None))
                elapsed = time.perf_counter() - started_at
                print(
                    f"[ranker] validation batch {batch_number}/{len(ranges)} complete "
                    f"({row_id_end - row_id_start:,} queries, "
                    f"elapsed {elapsed / 60:.1f} min)"
                )
        maps = {
            name: reciprocal_sum / validation_rows
            for name, reciprocal_sum in reciprocal_sums.items()
        }
        return validation_rows, positive_candidates / validation_rows, maps
    finally:
        con.close()


def train_and_validate_ranker(
    paths: ProjectPaths,
    *,
    train_start: date = date(2014, 1, 1),
    validation_cutoff: date = date(2014, 8, 1),
    max_train_queries: int = 100_000,
    max_eval_queries: int = 30_000,
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RankerMetrics:
    train_path = paths.processed_dir / "train.parquet"
    if not train_path.exists():
        raise FileNotFoundError("train.parquet is missing. Run prepare first.")
    if train_start >= validation_cutoff:
        raise ValueError("train_start must be earlier than validation_cutoff")
    paths.ensure_directories()

    print("[ranker] building temporal training features")
    train_frame = _load_training_frame(
        paths,
        history_cutoff=train_start,
        query_start=train_start,
        query_end=validation_cutoff,
        max_queries=max_train_queries,
        threads=threads,
        memory_limit=memory_limit,
        batch_size=batch_size,
    )
    print("[ranker] building stopping and calibration samples")
    eval_frame = _load_training_frame(
        paths,
        history_cutoff=validation_cutoff,
        query_start=validation_cutoff,
        query_end=date(2015, 1, 1),
        max_queries=max_eval_queries,
        threads=threads,
        memory_limit=memory_limit,
        batch_size=batch_size,
    )
    stopping_frame, calibration_frame = _split_eval_frame(eval_frame)
    del eval_frame

    print(
        f"[ranker] fitting LightGBM on {len(train_frame):,} candidate rows; "
        f"stopping={len(stopping_frame):,}; calibration={len(calibration_frame):,}"
    )
    model, train_queries_used, train_rows = _fit_ranker(
        train_frame,
        stopping_frame,
        threads=threads,
    )
    del train_frame, stopping_frame

    best_iteration = int(model.best_iteration_ or model.n_estimators_)
    weights, calibration = _tune_blend(
        model.booster_,
        calibration_frame,
        best_iteration,
    )
    del calibration_frame

    model_path = paths.artifacts_dir / "ranker_model.txt"
    metadata_path = paths.artifacts_dir / "ranker_model_metadata.json"
    importance_path = paths.artifacts_dir / "ranker_feature_importance.csv"
    model.booster_.save_model(str(model_path))
    metadata = {
        "pipeline_version": 2,
        "best_iteration": best_iteration,
        "features": list(RANKER_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "train_start": train_start.isoformat(),
        "validation_cutoff": validation_cutoff.isoformat(),
        "blend_weights": asdict(weights),
        "calibration_metrics": calibration,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_feature_importance(model, importance_path)

    print("[ranker] scoring the complete temporal validation set")
    validation_rows, recall_at_20, maps = _score_full_validation(
        paths,
        model_path=model_path,
        best_iteration=best_iteration,
        weights=weights,
        cutoff=validation_cutoff,
        threads=threads,
        memory_limit=memory_limit,
        batch_size=batch_size,
    )
    metrics = RankerMetrics(
        train_history_cutoff=train_start.isoformat(),
        train_query_start=train_start.isoformat(),
        train_query_end=validation_cutoff.isoformat(),
        validation_cutoff=validation_cutoff.isoformat(),
        train_queries_requested=max_train_queries,
        train_queries_used=train_queries_used,
        train_rows=train_rows,
        validation_rows=validation_rows,
        candidate_recall_at_20=recall_at_20,
        model_map_at_5=maps["model"],
        heuristic_map_at_5=maps["heuristic"],
        legacy_map_at_5=maps["legacy"],
        map_at_5=maps["blend"],
        best_iteration=best_iteration,
        model_weight=weights.model,
        heuristic_weight=weights.heuristic,
        legacy_weight=weights.legacy,
        calibration_map_at_5=float(calibration["blend"]),
        model_path=str(model_path),
    )
    metrics_path = paths.artifacts_dir / "ranker_validation_metrics.json"
    metrics_path.write_text(
        json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
    print(f"[ranker] model: {model_path}")
    print(f"[ranker] metrics: {metrics_path}")
    return metrics


def build_ranker_submission(
    paths: ProjectPaths,
    *,
    model_path: Path | None = None,
    threads: int = 4,
    memory_limit: str = "8GB",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Path:
    import lightgbm as lgb

    train_path = paths.processed_dir / "train.parquet"
    test_path = paths.processed_dir / "test.parquet"
    if not train_path.exists() or not test_path.exists():
        raise FileNotFoundError("Processed train/test files are missing. Run prepare first.")
    paths.ensure_directories()
    model_path = model_path or (paths.artifacts_dir / "ranker_model.txt")
    metadata_path = paths.artifacts_dir / "ranker_model_metadata.json"
    if not model_path.exists() or not metadata_path.exists():
        raise FileNotFoundError("Ranker model is missing. Run ranker-validate first.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if int(metadata.get("pipeline_version", 0)) != 2:
        raise RuntimeError("The saved model predates the blended ranker. Retrain it.")
    best_iteration = int(metadata.get("best_iteration", 0))
    weights = BlendWeights(**metadata["blend_weights"])
    model = lgb.Booster(model_file=str(model_path))
    submission_path = paths.artifacts_dir / "submission_ranker.csv"
    con = connect(
        paths.processed_dir / "ranker_submission.duckdb",
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
                frame = con.execute(
                    _feature_select_sql(row_id_start, row_id_end, include_label=False)
                ).fetch_df()
                frame = _optimize_frame(frame, include_label=False)
                components = _component_frame(model, frame, best_iteration)
                ranked = _rank_components(components, weights)
                top5 = ranked.loc[ranked["blend_rank"].le(5)]
                predicted = top5.groupby("row_id", sort=False)["candidate_cluster"].agg(
                    lambda values: " ".join(str(int(value)) for value in values)
                )
                ids = pd.DataFrame(
                    {"row_id": np.arange(row_id_start, row_id_end, dtype=np.int64)}
                ).merge(predicted.rename("hotel_cluster"), on="row_id", how="left")
                writer.writerows(ids.itertuples(index=False, name=None))
                elapsed = time.perf_counter() - started_at
                completed = batch_number / len(ranges)
                remaining = elapsed * (1.0 - completed) / completed
                print(
                    f"[ranker] submission batch {batch_number}/{len(ranges)} complete "
                    f"({row_id_end - row_id_start:,} rows, "
                    f"elapsed {elapsed / 60:.1f} min, ETA {remaining / 60:.1f} min)"
                )
        print(f"[ranker] submission: {submission_path}")
        return submission_path
    finally:
        con.close()
