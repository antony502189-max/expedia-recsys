from __future__ import annotations

import csv
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
    _create_period_query_rows,
    _create_test_rows,
    _create_validation_rows,
    _row_bounds,
    source_feature_names,
)
from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect

if TYPE_CHECKING:
    import duckdb
    import lightgbm as lgb


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
    map_at_5: float
    best_iteration: int
    model_path: str


BASE_FEATURES: tuple[str, ...] = (
    "candidate_cluster",
    "combined_score",
    "source_count",
    "strongest_source_score",
    "best_source_rank",
    "strongest_source_id",
    "heuristic_rank",
    "is_mobile",
    "is_package",
    "channel",
    "posa_continent",
    "user_location_country",
    "user_location_region",
    "srch_destination_type_id",
    "hotel_continent",
    "hotel_country",
    "hotel_market",
    "checkin_month",
    "search_month",
    "srch_adults_cnt",
    "srch_children_cnt",
    "srch_rm_cnt",
    "stay_nights",
    "booking_window_days",
)
RANKER_FEATURES: tuple[str, ...] = BASE_FEATURES + source_feature_names()
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "candidate_cluster",
    "strongest_source_id",
    "is_mobile",
    "is_package",
    "channel",
    "posa_continent",
    "user_location_country",
    "user_location_region",
    "srch_destination_type_id",
    "hotel_continent",
    "hotel_country",
    "hotel_market",
    "checkin_month",
    "search_month",
)
_INTEGER_FEATURES = set(CATEGORICAL_FEATURES) | {
    "source_count",
    "best_source_rank",
    "heuristic_rank",
    "srch_adults_cnt",
    "srch_children_cnt",
    "srch_rm_cnt",
    "stay_nights",
    "booking_window_days",
}
_INTEGER_FEATURES.update(
    name
    for name in source_feature_names()
    if name.endswith("_rank") or name.endswith("_present")
)


def _feature_select_sql(row_id_start: int, row_id_end: int, *, include_label: bool) -> str:
    source_columns = ",\n        ".join(f"c.{name}" for name in source_feature_names())
    label_columns = ""
    if include_label:
        label_columns = (
            ",\n        q.hotel_cluster::SMALLINT AS actual_hotel_cluster,"
            "\n        CASE WHEN q.hotel_cluster = c.hotel_cluster THEN 1 ELSE 0 END"
            "::TINYINT AS label"
        )
    return f"""
    SELECT
        c.row_id,
        c.hotel_cluster::SMALLINT AS candidate_cluster,
        c.combined_score,
        c.source_count,
        c.strongest_source_score,
        c.best_source_rank,
        c.strongest_source_id,
        c.final_rank::SMALLINT AS heuristic_rank,
        q.is_mobile,
        q.is_package,
        q.channel,
        q.posa_continent,
        q.user_location_country,
        q.user_location_region,
        q.srch_destination_type_id,
        q.hotel_continent,
        q.hotel_country,
        q.hotel_market,
        q.checkin_month,
        TRY_CAST(EXTRACT(month FROM q.date_time) AS SMALLINT) AS search_month,
        q.srch_adults_cnt,
        q.srch_children_cnt,
        q.srch_rm_cnt,
        COALESCE(DATE_DIFF('day', q.srch_ci, q.srch_co), -1)::SMALLINT AS stay_nights,
        COALESCE(DATE_DIFF('day', CAST(q.date_time AS DATE), q.srch_ci), -1)::SMALLINT
            AS booking_window_days,
        {source_columns}
        {label_columns}
    FROM competition_batch_candidates c
    JOIN competition_query_rows q USING (row_id)
    WHERE c.row_id >= {row_id_start}
      AND c.row_id < {row_id_end}
    ORDER BY c.row_id, c.final_rank
    """


def _optimize_frame(frame: pd.DataFrame, *, include_label: bool) -> pd.DataFrame:
    frame["row_id"] = frame["row_id"].astype("int64")
    for feature in RANKER_FEATURES:
        if feature in _INTEGER_FEATURES:
            frame[feature] = frame[feature].fillna(-1).astype("int32")
        else:
            frame[feature] = frame[feature].fillna(0.0).astype("float32")
    if include_label:
        frame["actual_hotel_cluster"] = frame["actual_hotel_cluster"].astype("int16")
        frame["label"] = frame["label"].astype("int8")
    return frame


def _collect_feature_frame(
    con: duckdb.DuckDBPyConnection,
    *,
    batch_size: int,
    include_label: bool,
) -> pd.DataFrame:
    start, stop, query_count = _row_bounds(con)
    if query_count == 0:
        raise RuntimeError("No query rows were created for ranker features.")
    frames: list[pd.DataFrame] = []
    ranges = list(_batch_ranges(start, stop, batch_size))
    started_at = time.perf_counter()
    for batch_number, (row_id_start, row_id_end) in enumerate(ranges, start=1):
        _create_candidate_batch(
            con,
            row_id_start=row_id_start,
            row_id_end=row_id_end,
        )
        frame = con.execute(
            _feature_select_sql(row_id_start, row_id_end, include_label=include_label)
        ).fetch_df()
        frames.append(_optimize_frame(frame, include_label=include_label))
        elapsed = time.perf_counter() - started_at
        print(
            f"[ranker] feature batch {batch_number}/{len(ranges)} complete "
            f"({len(frame):,} candidate rows, elapsed {elapsed / 60:.1f} min)"
        )
    return pd.concat(frames, ignore_index=True)


def _load_training_frame(
    paths: ProjectPaths,
    *,
    history_cutoff: date,
    query_start: date,
    query_end: date,
    max_queries: int,
    threads: int,
    memory_limit: str,
    batch_size: int,
) -> pd.DataFrame:
    train_path = paths.processed_dir / "train.parquet"
    con = connect(
        paths.processed_dir / "ranker_features.duckdb",
        threads=threads,
        memory_limit=memory_limit,
    )
    try:
        _create_history(con, train_path, history_cutoff)
        _create_period_query_rows(
            con,
            train_path,
            start=query_start,
            end=query_end,
            max_queries=max_queries,
        )
        _build_lookup_tables(con)
        return _collect_feature_frame(con, batch_size=batch_size, include_label=True)
    finally:
        con.close()


def _filter_trainable_groups(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    has_positive = frame.groupby("row_id", sort=False)["label"].transform("max").eq(1)
    filtered = frame.loc[has_positive].copy()
    group = filtered.groupby("row_id", sort=False).size().to_numpy(dtype=np.int32)
    if filtered.empty or int(group.sum()) != len(filtered):
        raise RuntimeError("Could not create valid LightGBM ranking groups.")
    return filtered, group


def _new_ranker(*, threads: int, n_estimators: int = 900) -> lgb.LGBMRanker:
    import lightgbm as lgb

    return lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        boosting_type="gbdt",
        n_estimators=n_estimators,
        learning_rate=0.035,
        num_leaves=63,
        max_depth=-1,
        min_child_samples=120,
        max_bin=127,
        subsample=0.85,
        subsample_freq=1,
        colsample_bytree=0.85,
        reg_alpha=0.15,
        reg_lambda=1.0,
        random_state=2026,
        n_jobs=threads,
        force_col_wise=True,
        lambdarank_truncation_level=20,
        label_gain=[0, 1],
        verbosity=-1,
    )


def _fit_ranker(
    train_frame: pd.DataFrame,
    eval_frame: pd.DataFrame,
    *,
    threads: int,
) -> tuple[lgb.LGBMRanker, int, int]:
    import lightgbm as lgb

    train_frame, train_group = _filter_trainable_groups(train_frame)
    eval_frame, eval_group = _filter_trainable_groups(eval_frame)
    model = _new_ranker(threads=threads)
    model.fit(
        train_frame.loc[:, RANKER_FEATURES],
        train_frame["label"],
        group=train_group,
        eval_set=[(eval_frame.loc[:, RANKER_FEATURES], eval_frame["label"])],
        eval_group=[eval_group],
        eval_at=[1, 3, 5],
        categorical_feature=list(CATEGORICAL_FEATURES),
        callbacks=[
            lgb.early_stopping(60, first_metric_only=True, verbose=True),
            lgb.log_evaluation(25),
        ],
    )
    return model, len(train_group), len(train_frame)


def _write_feature_importance(model: lgb.LGBMRanker, target: Path) -> None:
    importance = pd.DataFrame(
        {
            "feature": list(RANKER_FEATURES),
            "gain": model.booster_.feature_importance(importance_type="gain"),
            "split": model.booster_.feature_importance(importance_type="split"),
        }
    ).sort_values("gain", ascending=False)
    importance.to_csv(target, index=False)


def _predict_frame(
    model: lgb.Booster,
    frame: pd.DataFrame,
    best_iteration: int,
) -> pd.DataFrame:
    prediction = model.predict(
        frame.loc[:, RANKER_FEATURES],
        num_iteration=best_iteration if best_iteration > 0 else None,
    )
    columns = ["row_id", "candidate_cluster"]
    if "label" in frame:
        columns.append("label")
    ranked = frame.loc[:, columns].copy()
    ranked["prediction"] = np.asarray(prediction, dtype=np.float32)
    ranked.sort_values(
        ["row_id", "prediction", "candidate_cluster"],
        ascending=[True, False, True],
        inplace=True,
        kind="mergesort",
    )
    ranked["model_rank"] = ranked.groupby("row_id", sort=False).cumcount() + 1
    return ranked


def _score_full_validation(
    paths: ProjectPaths,
    *,
    model_path: Path,
    best_iteration: int,
    cutoff: date,
    threads: int,
    memory_limit: str,
    batch_size: int,
) -> tuple[int, float, float]:
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
        hit_at_20 = 0
        reciprocal_rank_sum = 0.0
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
                ranked = _predict_frame(model, frame, best_iteration)
                positives = ranked.loc[ranked["label"].eq(1)]
                hit_at_20 += len(positives)
                top5_positive = positives.loc[
                    positives["model_rank"].le(5), "model_rank"
                ]
                reciprocal_rank_sum += float((1.0 / top5_positive).sum())
                actual = frame.loc[
                    :, ["row_id", "actual_hotel_cluster"]
                ].drop_duplicates("row_id")
                top5 = ranked.loc[ranked["model_rank"].le(5)]
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
        return (
            validation_rows,
            hit_at_20 / validation_rows,
            reciprocal_rank_sum / validation_rows,
        )
    finally:
        con.close()


def train_and_validate_ranker(
    paths: ProjectPaths,
    *,
    train_start: date = date(2014, 5, 1),
    validation_cutoff: date = date(2014, 8, 1),
    max_train_queries: int = 100_000,
    max_eval_queries: int = 25_000,
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
    print("[ranker] building early-stopping validation sample")
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
    print(
        f"[ranker] fitting LightGBM on {len(train_frame):,} candidate rows; "
        f"eval={len(eval_frame):,}"
    )
    model, train_queries_used, train_rows = _fit_ranker(
        train_frame,
        eval_frame,
        threads=threads,
    )
    del train_frame, eval_frame
    model_path = paths.artifacts_dir / "ranker_model.txt"
    metadata_path = paths.artifacts_dir / "ranker_model_metadata.json"
    importance_path = paths.artifacts_dir / "ranker_feature_importance.csv"
    model.booster_.save_model(str(model_path))
    best_iteration = int(model.best_iteration_ or model.n_estimators_)
    metadata_path.write_text(
        json.dumps(
            {
                "best_iteration": best_iteration,
                "features": list(RANKER_FEATURES),
                "categorical_features": list(CATEGORICAL_FEATURES),
                "train_start": train_start.isoformat(),
                "validation_cutoff": validation_cutoff.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_feature_importance(model, importance_path)
    print("[ranker] scoring the complete temporal validation set")
    validation_rows, recall_at_20, map_at_5 = _score_full_validation(
        paths,
        model_path=model_path,
        best_iteration=best_iteration,
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
        map_at_5=map_at_5,
        best_iteration=best_iteration,
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
    best_iteration = int(metadata.get("best_iteration", 0))
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
                ranked = _predict_frame(model, frame, best_iteration)
                top5 = ranked.loc[ranked["model_rank"].le(5)]
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
