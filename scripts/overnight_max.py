from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
PROCESSED = ROOT / "data" / "processed"
CHAMPION_FILES = (
    "ranker_model.txt",
    "ranker_model_metadata.json",
    "ranker_validation_metrics.json",
    "ranker_validation_predictions.csv",
    "ranker_feature_importance.csv",
)
EXPECTED_TEST_ROWS = 2_528_243


@dataclass(frozen=True, slots=True)
class Experiment:
    name: str
    train_start: str
    max_train_queries: int
    max_eval_queries: int = 50_000


@dataclass(slots=True)
class CommandResult:
    name: str
    command: list[str]
    return_code: int | None
    elapsed_seconds: float
    timed_out: bool
    log_path: str


@dataclass(slots=True)
class ModelRun:
    name: str
    directory: Path
    source: str
    train_start: str | None = None
    max_train_queries: int | None = None
    elapsed_seconds: float = 0.0
    metrics: dict[str, Any] | None = None
    fusion_metrics: dict[str, Any] | None = None
    prediction_full_map: float | None = None
    prediction_calibration_map: float | None = None
    prediction_evaluation_map: float | None = None
    error: str | None = None


class Reporter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")


@contextmanager
def prevent_windows_sleep() -> Any:
    if os.name != "nt":
        yield
        return
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    es_awaymode_required = 0x00000040
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(
        es_continuous | es_system_required | es_awaymode_required
    )
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(es_continuous)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a time-budgeted overnight Expedia model search."
    )
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--threads", type=int, default=7)
    parser.add_argument("--memory-limit", default="32GB")
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument(
        "--skip-submission",
        action="store_true",
        help="Skip final test-set scoring and only compare validation results.",
    )
    return parser.parse_args()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def archive_ranker(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in CHAMPION_FILES:
        copy_if_exists(ARTIFACTS / name, target / name)


def run_command(
    reporter: Reporter,
    run_dir: Path,
    name: str,
    command: list[str],
    *,
    timeout_seconds: float,
) -> CommandResult:
    log_path = run_dir / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    reporter.write(f"START {name}: {' '.join(command)}")
    started = time.monotonic()
    return_code: int | None = None
    timed_out = False
    with log_path.open("w", encoding="utf-8", errors="replace") as output:
        output.write("COMMAND: " + " ".join(command) + "\n\n")
        output.flush()
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, timeout_seconds),
                check=False,
            )
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            output.write("\nTIMEOUT: command exceeded its time budget.\n")
        except OSError as exc:
            output.write(f"\nOS ERROR: {exc}\n")
    elapsed = time.monotonic() - started
    state = "TIMEOUT" if timed_out else f"exit={return_code}"
    reporter.write(f"END {name}: {state}, {elapsed / 60:.1f} min")
    return CommandResult(
        name=name,
        command=command,
        return_code=return_code,
        elapsed_seconds=elapsed,
        timed_out=timed_out,
        log_path=str(log_path),
    )


def uv_command(args: argparse.Namespace, subcommand: list[str]) -> list[str]:
    return [
        "uv",
        "run",
        "expedia-recsys",
        "--threads",
        str(args.threads),
        "--memory-limit",
        args.memory_limit,
        *subcommand,
    ]


def hardware_snapshot() -> dict[str, Any]:
    disk = shutil.disk_usage(ROOT)
    snapshot: dict[str, Any] = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "project_drive_total_gb": round(disk.total / 1024**3, 2),
        "project_drive_free_gb": round(disk.free / 1024**3, 2),
    }
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            snapshot["ram_total_gb"] = round(status.total_physical / 1024**3, 2)
            snapshot["ram_available_gb"] = round(
                status.available_physical / 1024**3, 2
            )
    return snapshot


def validate_environment(reporter: Reporter) -> None:
    required = (
        PROCESSED / "train.parquet",
        PROCESSED / "test.parquet",
        ARTIFACTS / "ranker_model.txt",
        ARTIFACTS / "ranker_model_metadata.json",
        ARTIFACTS / "ranker_validation_metrics.json",
        ARTIFACTS / "ranker_validation_predictions.csv",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required files:\n" + "\n".join(missing))
    free_gb = shutil.disk_usage(ROOT).free / 1024**3
    if free_gb < 80:
        raise RuntimeError(f"At least 80 GB free disk space is required; found {free_gb:.1f} GB.")
    reporter.write("Environment validation passed.")


def run_geo_fusion(
    reporter: Reporter,
    run_dir: Path,
    args: argparse.Namespace,
    model_run: ModelRun,
    *,
    timeout_seconds: float,
) -> CommandResult:
    prediction_path = model_run.directory / "ranker_validation_predictions.csv"
    result = run_command(
        reporter,
        run_dir,
        f"fusion_{model_run.name}",
        uv_command(
            args,
            [
                "geo-fusion-validate",
                "--cutoff",
                "2014-08-01",
                "--champion",
                str(prediction_path),
                "--batch-size",
                str(args.batch_size),
            ],
        ),
        timeout_seconds=timeout_seconds,
    )
    if result.return_code == 0 and not result.timed_out:
        source = ARTIFACTS / "geo_fusion_validation_metrics.json"
        target = model_run.directory / "geo_fusion_validation_metrics.json"
        copy_if_exists(source, target)
        model_run.fusion_metrics = load_json(target)
    return result


def prediction_arrays(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_csv(
        path,
        usecols=["row_id", "actual_hotel_cluster", "hotel_cluster"],
        dtype={"row_id": "int64", "actual_hotel_cluster": "int16", "hotel_cluster": "string"},
    )
    split = frame["hotel_cluster"].fillna("").str.split(expand=True)
    split = split.reindex(columns=range(5), fill_value="-1")
    predictions = split.fillna("-1").astype("int16").to_numpy(copy=True)
    return (
        frame["row_id"].to_numpy(dtype=np.int64, copy=True),
        frame["actual_hotel_cluster"].to_numpy(dtype=np.int16, copy=True),
        predictions,
    )


def reciprocal_ranks(actual: np.ndarray, predictions: np.ndarray) -> np.ndarray:
    result = np.zeros(len(actual), dtype=np.float32)
    for rank in range(min(5, predictions.shape[1])):
        mask = (result == 0.0) & (predictions[:, rank] == actual)
        result[mask] = 1.0 / float(rank + 1)
    return result


def evaluate_single_predictions(model_runs: list[ModelRun], reporter: Reporter) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    reference_rows: np.ndarray | None = None
    reference_actual: np.ndarray | None = None
    for model_run in model_runs:
        path = model_run.directory / "ranker_validation_predictions.csv"
        if not path.exists():
            continue
        row_ids, actual, predictions = prediction_arrays(path)
        if reference_rows is None:
            reference_rows = row_ids
            reference_actual = actual
        elif not np.array_equal(reference_rows, row_ids) or not np.array_equal(
            reference_actual, actual
        ):
            model_run.error = "Validation prediction rows are not aligned."
            continue
        rr = reciprocal_ranks(actual, predictions)
        calibration = (row_ids & 1) == 0
        evaluation = ~calibration
        model_run.prediction_full_map = float(rr.mean())
        model_run.prediction_calibration_map = float(rr[calibration].mean())
        model_run.prediction_evaluation_map = float(rr[evaluation].mean())
        arrays[model_run.name] = predictions
        reporter.write(
            f"MODEL {model_run.name}: full={model_run.prediction_full_map:.9f}, "
            f"cal={model_run.prediction_calibration_map:.9f}, "
            f"eval={model_run.prediction_evaluation_map:.9f}"
        )
    if reference_rows is None or reference_actual is None:
        raise RuntimeError("No aligned validation prediction files were found.")
    arrays["__row_ids__"] = reference_rows
    arrays["__actual__"] = reference_actual
    return arrays


def rrf_predictions(
    prediction_arrays_by_name: dict[str, np.ndarray],
    model_names: list[str],
    weights: list[float],
    *,
    k: float,
    chunk_size: int = 100_000,
) -> np.ndarray:
    row_ids = prediction_arrays_by_name["__row_ids__"]
    output = np.empty((len(row_ids), 5), dtype=np.int16)
    cluster_tie_break = (99 - np.arange(100, dtype=np.float32)) * 1e-8
    for start in range(0, len(row_ids), chunk_size):
        stop = min(start + chunk_size, len(row_ids))
        size = stop - start
        scores = np.zeros((size, 100), dtype=np.float32)
        scores += cluster_tie_break
        rows = np.arange(size, dtype=np.int64)
        for model_name, weight in zip(model_names, weights, strict=True):
            predictions = prediction_arrays_by_name[model_name][start:stop]
            for rank in range(5):
                clusters = predictions[:, rank]
                valid = (clusters >= 0) & (clusters < 100)
                scores[rows[valid], clusters[valid]] += float(weight) / (k + rank + 1.0)
        top = np.argpartition(-scores, kth=4, axis=1)[:, :5]
        top_scores = np.take_along_axis(scores, top, axis=1)
        order = np.argsort(-top_scores, axis=1, kind="stable")
        output[start:stop] = np.take_along_axis(top, order, axis=1).astype(np.int16)
    return output


def ensemble_configurations(sorted_names: list[str]) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    templates = {
        2: ([1.0, 1.0], [2.0, 1.0]),
        3: ([1.0, 1.0, 1.0], [3.0, 2.0, 1.0]),
        4: ([1.0, 1.0, 1.0, 1.0], [4.0, 3.0, 2.0, 1.0]),
    }
    for count, weight_sets in templates.items():
        if len(sorted_names) < count:
            continue
        names = sorted_names[:count]
        for weights in weight_sets:
            for k in (0.0, 5.0):
                configs.append(
                    {
                        "name": f"rrf_top{count}_{'-'.join(str(int(v)) for v in weights)}_k{int(k)}",
                        "models": names,
                        "weights": list(weights),
                        "k": k,
                    }
                )
    return configs


def tune_ensemble(
    model_runs: list[ModelRun],
    arrays: dict[str, np.ndarray],
    reporter: Reporter,
    run_dir: Path,
) -> dict[str, Any] | None:
    available = [
        model_run
        for model_run in model_runs
        if model_run.name in arrays and model_run.prediction_full_map is not None
    ]
    if len(available) < 2:
        return None
    available.sort(
        key=lambda item: (
            item.prediction_calibration_map or -1.0,
            item.prediction_full_map or -1.0,
        ),
        reverse=True,
    )
    names = [item.name for item in available]
    row_ids = arrays["__row_ids__"]
    actual = arrays["__actual__"]
    calibration = (row_ids & 1) == 0
    evaluation = ~calibration
    candidates: list[dict[str, Any]] = []
    for config in ensemble_configurations(names):
        predicted = rrf_predictions(
            arrays,
            config["models"],
            config["weights"],
            k=float(config["k"]),
        )
        rr = reciprocal_ranks(actual, predicted)
        candidate = {
            **config,
            "calibration_map_at_5": float(rr[calibration].mean()),
            "evaluation_map_at_5": float(rr[evaluation].mean()),
            "full_map_at_5": float(rr.mean()),
        }
        candidates.append(candidate)
        reporter.write(
            f"ENSEMBLE {candidate['name']}: "
            f"cal={candidate['calibration_map_at_5']:.9f}, "
            f"eval={candidate['evaluation_map_at_5']:.9f}, "
            f"full={candidate['full_map_at_5']:.9f}"
        )
    best = max(
        candidates,
        key=lambda item: (
            item["calibration_map_at_5"],
            item["evaluation_map_at_5"],
            item["full_map_at_5"],
            -len(item["models"]),
        ),
    )
    best_predictions = rrf_predictions(
        arrays,
        best["models"],
        best["weights"],
        k=float(best["k"]),
    )
    output_path = run_dir / "ensemble_validation_predictions.csv"
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["row_id", "actual_hotel_cluster", "hotel_cluster"])
        for row_id, cluster, predictions in zip(
            row_ids, actual, best_predictions, strict=True
        ):
            writer.writerow(
                [
                    int(row_id),
                    int(cluster),
                    " ".join(str(int(value)) for value in predictions),
                ]
            )
    payload = {"best": best, "candidates": candidates}
    (run_dir / "ensemble_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return best


def write_rrf_submission(
    paths: list[Path],
    names: list[str],
    weights: list[float],
    *,
    k: float,
    target: Path,
) -> None:
    arrays: dict[str, np.ndarray] = {}
    reference_ids: np.ndarray | None = None
    for name, path in zip(names, paths, strict=True):
        frame = pd.read_csv(
            path,
            usecols=["id", "hotel_cluster"],
            dtype={"id": "int64", "hotel_cluster": "string"},
        )
        ids = frame["id"].to_numpy(dtype=np.int64, copy=True)
        if reference_ids is None:
            reference_ids = ids
        elif not np.array_equal(reference_ids, ids):
            raise RuntimeError("Test submission IDs are not aligned.")
        split = frame["hotel_cluster"].fillna("").str.split(expand=True)
        split = split.reindex(columns=range(5), fill_value="-1")
        arrays[name] = split.fillna("-1").astype("int16").to_numpy(copy=True)
    if reference_ids is None:
        raise RuntimeError("No submission files were supplied for blending.")
    arrays["__row_ids__"] = reference_ids
    predicted = rrf_predictions(arrays, names, weights, k=k)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["id", "hotel_cluster"])
        for row_id, predictions in zip(reference_ids, predicted, strict=True):
            writer.writerow(
                [int(row_id), " ".join(str(int(value)) for value in predictions)]
            )


def validate_submission(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path, dtype={"id": "int64", "hotel_cluster": "string"})
    split = frame["hotel_cluster"].fillna("").str.split()
    lengths = split.str.len()
    unique = split.map(lambda values: len(set(values)) if values else 0)
    result = {
        "path": str(path),
        "rows": int(len(frame)),
        "unique_ids": int(frame["id"].nunique()),
        "five_predictions_all": bool(lengths.eq(5).all()),
        "five_unique_predictions_all": bool(unique.eq(5).all()),
        "null_count": int(frame.isna().sum().sum()),
    }
    if result["rows"] != EXPECTED_TEST_ROWS:
        raise RuntimeError(
            f"Submission row count is {result['rows']:,}; expected {EXPECTED_TEST_ROWS:,}."
        )
    if not result["five_predictions_all"] or not result["five_unique_predictions_all"]:
        raise RuntimeError("Submission contains invalid top-5 predictions.")
    return result


def restore_model(model_run: ModelRun) -> None:
    for name in CHAMPION_FILES:
        copy_if_exists(model_run.directory / name, ARTIFACTS / name)


def build_final_submission(
    reporter: Reporter,
    run_dir: Path,
    args: argparse.Namespace,
    deadline: float,
    selected_single: ModelRun,
    selected_ensemble: dict[str, Any] | None,
    models_by_name: dict[str, ModelRun],
) -> tuple[Path | None, dict[str, Any] | None]:
    if args.skip_submission:
        reporter.write("Final submission generation skipped by command-line flag.")
        return None, None

    if selected_ensemble is None:
        required_names = [selected_single.name]
    else:
        required_names = list(selected_ensemble["models"])

    submission_paths: list[Path] = []
    generated_names: list[str] = []
    for model_name in required_names:
        remaining = deadline - time.monotonic()
        if remaining < 20 * 60:
            reporter.write("Not enough time remains to score another test model.")
            break
        model_run = models_by_name[model_name]
        metadata = model_run.directory / "ranker_model_metadata.json"
        model = model_run.directory / "ranker_model.txt"
        if not metadata.exists() or not model.exists():
            reporter.write(f"Cannot score {model_name}: model files are missing.")
            continue
        copy_if_exists(metadata, ARTIFACTS / "ranker_model_metadata.json")
        result = run_command(
            reporter,
            run_dir,
            f"submit_{model_name}",
            uv_command(
                args,
                [
                    "ranker-submit",
                    "--model",
                    str(model),
                    "--batch-size",
                    str(args.batch_size),
                ],
            ),
            timeout_seconds=max(60.0, deadline - time.monotonic() - 5 * 60),
        )
        if result.return_code != 0 or result.timed_out:
            continue
        target = model_run.directory / "submission_ranker.csv"
        copy_if_exists(ARTIFACTS / "submission_ranker.csv", target)
        if target.exists():
            submission_paths.append(target)
            generated_names.append(model_name)

    final_path = ARTIFACTS / "submission_overnight_best.csv"
    if selected_ensemble is not None and generated_names == required_names:
        write_rrf_submission(
            submission_paths,
            generated_names,
            list(selected_ensemble["weights"]),
            k=float(selected_ensemble["k"]),
            target=final_path,
        )
    elif selected_single.name in generated_names:
        source = submission_paths[generated_names.index(selected_single.name)]
        shutil.copy2(source, final_path)
    elif submission_paths:
        shutil.copy2(submission_paths[0], final_path)
    else:
        reporter.write("No final test submission was generated.")
        return None, None

    validation = validate_submission(final_path)
    copy_if_exists(final_path, run_dir / "final_submission.csv")
    reporter.write(f"Final submission ready: {final_path}")
    return final_path, validation


def main() -> int:
    args = parse_args()
    if args.hours <= 0 or args.threads <= 0 or args.batch_size <= 0:
        raise ValueError("hours, threads and batch-size must be positive")

    run_dir = ARTIFACTS / "overnight_max" / utc_stamp()
    run_dir.mkdir(parents=True, exist_ok=False)
    reporter = Reporter(run_dir / "overnight.log")
    started = time.monotonic()
    deadline = started + args.hours * 3600
    reserve_final_seconds = 115 * 60
    commands: list[CommandResult] = []
    model_runs: list[ModelRun] = []
    errors: list[str] = []
    final_path: Path | None = None
    submission_validation: dict[str, Any] | None = None

    experiments = (
        Experiment("balanced_350k", "2014-01-01", 350_000),
        Experiment("recent_320k", "2014-02-15", 320_000),
        Experiment("long_history_320k", "2013-10-01", 320_000),
        Experiment("recent_focus_280k", "2014-04-01", 280_000),
    )

    try:
        reporter.write(f"Overnight run directory: {run_dir}")
        reporter.write(
            f"Budget={args.hours:.2f}h, threads={args.threads}, "
            f"memory={args.memory_limit}, batch={args.batch_size:,}"
        )
        validate_environment(reporter)
        hardware = hardware_snapshot()
        (run_dir / "hardware.json").write_text(
            json.dumps(hardware, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reporter.write("Hardware: " + json.dumps(hardware, ensure_ascii=False))

        current_dir = run_dir / "models" / "current_champion"
        archive_ranker(current_dir)
        current = ModelRun(
            name="current_champion",
            directory=current_dir,
            source="existing",
            metrics=load_json(current_dir / "ranker_validation_metrics.json"),
        )
        model_runs.append(current)

        checks = (
            ("ruff", ["uv", "run", "ruff", "check", "."], 10 * 60),
            ("pytest", ["uv", "run", "pytest"], 20 * 60),
        )
        for name, command, timeout in checks:
            result = run_command(
                reporter, run_dir, name, command, timeout_seconds=timeout
            )
            commands.append(result)
            if result.return_code != 0 or result.timed_out:
                raise RuntimeError(f"Required check failed: {name}. See {result.log_path}")

        commands.append(
            run_geo_fusion(
                reporter,
                run_dir,
                args,
                current,
                timeout_seconds=min(40 * 60, max(60.0, deadline - time.monotonic())),
            )
        )

        training_durations: list[float] = []
        for experiment in experiments:
            remaining = deadline - time.monotonic()
            estimated_training = (
                statistics.median(training_durations) * 1.15
                if training_durations
                else 75 * 60
            )
            estimated_total = estimated_training + 35 * 60
            if remaining - reserve_final_seconds < estimated_total:
                reporter.write(
                    f"Skipping {experiment.name}: preserving time for model comparison "
                    "and final submission."
                )
                break

            experiment_dir = run_dir / "models" / experiment.name
            model_run = ModelRun(
                name=experiment.name,
                directory=experiment_dir,
                source="overnight",
                train_start=experiment.train_start,
                max_train_queries=experiment.max_train_queries,
            )
            model_runs.append(model_run)
            timeout = min(
                135 * 60,
                max(30 * 60, deadline - time.monotonic() - reserve_final_seconds - 30 * 60),
            )
            result = run_command(
                reporter,
                run_dir,
                f"train_{experiment.name}",
                uv_command(
                    args,
                    [
                        "ranker-validate",
                        "--train-start",
                        experiment.train_start,
                        "--cutoff",
                        "2014-08-01",
                        "--max-train-queries",
                        str(experiment.max_train_queries),
                        "--max-eval-queries",
                        str(experiment.max_eval_queries),
                        "--batch-size",
                        str(args.batch_size),
                    ],
                ),
                timeout_seconds=timeout,
            )
            commands.append(result)
            model_run.elapsed_seconds = result.elapsed_seconds
            if result.return_code != 0 or result.timed_out:
                model_run.error = f"Training failed. See {result.log_path}"
                continue
            training_durations.append(result.elapsed_seconds)
            archive_ranker(experiment_dir)
            model_run.metrics = load_json(
                experiment_dir / "ranker_validation_metrics.json"
            )
            fusion_remaining = deadline - time.monotonic() - reserve_final_seconds
            if fusion_remaining >= 8 * 60:
                commands.append(
                    run_geo_fusion(
                        reporter,
                        run_dir,
                        args,
                        model_run,
                        timeout_seconds=min(35 * 60, fusion_remaining),
                    )
                )

        successful = [
            model_run
            for model_run in model_runs
            if (model_run.directory / "ranker_validation_predictions.csv").exists()
        ]
        arrays = evaluate_single_predictions(successful, reporter)
        ensemble = tune_ensemble(successful, arrays, reporter, run_dir)

        successful.sort(
            key=lambda item: (
                item.prediction_evaluation_map or -1.0,
                item.prediction_full_map or -1.0,
            ),
            reverse=True,
        )
        selected_single = successful[0]
        selected_ensemble: dict[str, Any] | None = None
        if ensemble is not None:
            single_eval = selected_single.prediction_evaluation_map or -1.0
            single_full = selected_single.prediction_full_map or -1.0
            if (
                ensemble["evaluation_map_at_5"] > single_eval
                and ensemble["full_map_at_5"] >= single_full
            ):
                selected_ensemble = ensemble
                reporter.write(
                    f"Selected ensemble {ensemble['name']} over single "
                    f"{selected_single.name}."
                )
            else:
                reporter.write(
                    f"Ensemble did not pass evaluation gate; selected single "
                    f"{selected_single.name}."
                )

        models_by_name = {model_run.name: model_run for model_run in successful}
        final_path, submission_validation = build_final_submission(
            reporter,
            run_dir,
            args,
            deadline,
            selected_single,
            selected_ensemble,
            models_by_name,
        )
        restore_model(selected_single)

        summary = {
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_hours": (time.monotonic() - started) / 3600,
            "configuration": vars(args),
            "hardware": hardware,
            "models": [
                {
                    **asdict(model_run),
                    "directory": str(model_run.directory),
                }
                for model_run in model_runs
            ],
            "selected_single": selected_single.name,
            "selected_ensemble": selected_ensemble,
            "final_submission": str(final_path) if final_path else None,
            "submission_validation": submission_validation,
            "commands": [asdict(command) for command in commands],
            "errors": errors,
        }
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        latest_path = ARTIFACTS / "overnight_max" / "latest_summary.json"
        shutil.copy2(summary_path, latest_path)

        lines = [
            "OVERNIGHT EXPEDIA SEARCH COMPLETE",
            f"Elapsed: {summary['elapsed_hours']:.2f} hours",
            f"Best single: {selected_single.name}",
            f"Best single evaluation MAP@5: {selected_single.prediction_evaluation_map:.9f}",
            f"Best single full MAP@5: {selected_single.prediction_full_map:.9f}",
            f"Selected ensemble: {selected_ensemble['name'] if selected_ensemble else 'none'}",
            f"Final submission: {final_path if final_path else 'not generated'}",
            f"Detailed summary: {summary_path}",
        ]
        text = "\n".join(lines) + "\n"
        (run_dir / "RESULT.txt").write_text(text, encoding="utf-8")
        (ARTIFACTS / "overnight_max" / "LATEST_RESULT.txt").write_text(
            text, encoding="utf-8"
        )
        reporter.write(text.replace("\n", " | ").strip(" |"))
        return 0
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        error_text = traceback.format_exc()
        (run_dir / "FAILED.txt").write_text(error_text, encoding="utf-8")
        reporter.write(f"FAILED: {type(exc).__name__}: {exc}")
        reporter.write(f"Traceback: {run_dir / 'FAILED.txt'}")
        return 1


if __name__ == "__main__":
    with prevent_windows_sleep():
        sys.exit(main())
