from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from overnight_max import (
    ARTIFACTS,
    CHAMPION_FILES,
    CommandResult,
    ModelRun,
    Reporter,
    archive_ranker,
    copy_if_exists,
    evaluate_single_predictions,
    hardware_snapshot,
    load_json,
    prevent_windows_sleep,
    reciprocal_ranks,
    restore_model,
    rrf_predictions,
    run_command,
    utc_stamp,
    uv_command,
    validate_environment,
    validate_submission,
    write_rrf_submission,
)


@dataclass(frozen=True, slots=True)
class DeepExperiment:
    name: str
    train_start: str
    max_train_queries: int
    max_eval_queries: int = 60_000


EXPERIMENTS: tuple[DeepExperiment, ...] = (
    DeepExperiment("history_aug_450k", "2013-08-01", 450_000),
    DeepExperiment("history_sep_475k", "2013-09-01", 475_000),
    DeepExperiment("history_sep15_500k", "2013-09-15", 500_000),
    DeepExperiment("history_oct_450k", "2013-10-01", 450_000),
    DeepExperiment("history_oct_550k", "2013-10-01", 550_000),
    DeepExperiment("history_oct15_500k", "2013-10-15", 500_000),
    DeepExperiment("history_nov_500k", "2013-11-01", 500_000),
    DeepExperiment("history_dec_500k", "2013-12-01", 500_000),
    DeepExperiment("balanced_jan_500k", "2014-01-01", 500_000),
    DeepExperiment("balanced_jan15_475k", "2014-01-15", 475_000),
    DeepExperiment("recent_feb_450k", "2014-02-01", 450_000),
    DeepExperiment("recent_mar_400k", "2014-03-01", 400_000),
    DeepExperiment("recent_apr_350k", "2014-04-01", 350_000),
    DeepExperiment("wide_history_500k", "2013-06-01", 500_000),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an adaptive five-to-six-hour Expedia deep model search."
    )
    parser.add_argument("--hours", type=float, default=6.0)
    parser.add_argument("--threads", type=int, default=7)
    parser.add_argument("--memory-limit", default="32GB")
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--max-new-submissions", type=int, default=5)
    parser.add_argument(
        "--skip-submission",
        action="store_true",
        help="Only compare validation predictions and skip test scoring.",
    )
    return parser.parse_args()


def copy_model_run(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in (*CHAMPION_FILES, "submission_ranker.csv"):
        copy_if_exists(source / name, target / name)


def import_previous_candidates(
    reporter: Reporter,
    run_dir: Path,
) -> list[ModelRun]:
    summary_path = ARTIFACTS / "overnight_max" / "latest_summary.json"
    summary = load_json(summary_path)
    imported: list[ModelRun] = []
    if summary is None:
        reporter.write("No previous overnight summary found; continuing without imports.")
        return imported

    previous_run_dir: Path | None = None
    models = summary.get("models", [])
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            source_text = item.get("directory")
            source = Path(source_text) if isinstance(source_text, str) else None
            if source is None or not (
                source / "ranker_validation_predictions.csv"
            ).exists():
                continue
            previous_run_dir = source.parent.parent
            name = f"prior_{item.get('name', source.name)}"
            target = run_dir / "models" / name
            copy_model_run(source, target)
            imported.append(
                ModelRun(
                    name=name,
                    directory=target,
                    source="previous_overnight",
                    train_start=(
                        str(item["train_start"])
                        if item.get("train_start") is not None
                        else None
                    ),
                    max_train_queries=(
                        int(item["max_train_queries"])
                        if item.get("max_train_queries") is not None
                        else None
                    ),
                    metrics=load_json(target / "ranker_validation_metrics.json"),
                )
            )

    ensemble_source = (
        previous_run_dir / "ensemble_validation_predictions.csv"
        if previous_run_dir is not None
        else None
    )
    test_source = ARTIFACTS / "submission_overnight_best.csv"
    if ensemble_source is not None and ensemble_source.exists() and test_source.exists():
        target = run_dir / "models" / "frozen_overnight_ensemble"
        target.mkdir(parents=True, exist_ok=True)
        copy_if_exists(
            ensemble_source,
            target / "ranker_validation_predictions.csv",
        )
        copy_if_exists(test_source, target / "submission_ranker.csv")
        imported.append(
            ModelRun(
                name="frozen_overnight_ensemble",
                directory=target,
                source="frozen_submission",
            )
        )
        reporter.write("Imported the Kaggle 0.51019 frozen overnight ensemble.")

    reporter.write(f"Imported {len(imported)} previous validation candidates.")
    return imported


def prediction_digest(predictions: np.ndarray) -> str:
    return hashlib.blake2b(predictions.tobytes(), digest_size=12).hexdigest()


def remove_duplicate_predictions(
    model_runs: list[ModelRun],
    arrays: dict[str, np.ndarray],
    reporter: Reporter,
) -> tuple[list[ModelRun], dict[str, np.ndarray]]:
    ordered = sorted(
        model_runs,
        key=lambda item: (
            item.prediction_calibration_map or -1.0,
            item.prediction_evaluation_map or -1.0,
            item.prediction_full_map or -1.0,
        ),
        reverse=True,
    )
    seen: dict[str, str] = {}
    unique: list[ModelRun] = []
    filtered: dict[str, np.ndarray] = {
        "__row_ids__": arrays["__row_ids__"],
        "__actual__": arrays["__actual__"],
    }
    for model_run in ordered:
        predictions = arrays.get(model_run.name)
        if predictions is None:
            continue
        digest = prediction_digest(predictions)
        duplicate = seen.get(digest)
        if duplicate is not None:
            reporter.write(
                f"DEDUP {model_run.name}: identical predictions to {duplicate}."
            )
            continue
        seen[digest] = model_run.name
        unique.append(model_run)
        filtered[model_run.name] = predictions
    return unique, filtered


def score_configuration(
    arrays: dict[str, np.ndarray],
    names: list[str],
    weights: list[float],
    k: float,
) -> dict[str, Any]:
    row_ids = arrays["__row_ids__"]
    actual = arrays["__actual__"]
    predictions = rrf_predictions(arrays, names, weights, k=k)
    rr = reciprocal_ranks(actual, predictions)
    calibration = (row_ids & 1) == 0
    evaluation = ~calibration
    return {
        "name": (
            f"deep_rrf_{len(names)}_"
            + "-".join(names)
            + "_w"
            + "-".join(f"{weight:g}" for weight in weights)
            + f"_k{k:g}"
        ),
        "models": list(names),
        "weights": list(weights),
        "k": float(k),
        "calibration_map_at_5": float(rr[calibration].mean()),
        "evaluation_map_at_5": float(rr[evaluation].mean()),
        "full_map_at_5": float(rr.mean()),
    }


def tune_deep_ensemble(
    model_runs: list[ModelRun],
    arrays: dict[str, np.ndarray],
    reporter: Reporter,
    run_dir: Path,
) -> dict[str, Any] | None:
    available = [
        item
        for item in model_runs
        if item.name in arrays and item.prediction_calibration_map is not None
    ]
    if len(available) < 2:
        return None
    available.sort(
        key=lambda item: (
            item.prediction_calibration_map or -1.0,
            item.prediction_evaluation_map or -1.0,
            item.prediction_full_map or -1.0,
        ),
        reverse=True,
    )
    pool = available[:8]
    candidates: list[dict[str, Any]] = []

    for count in range(2, min(5, len(pool)) + 1):
        names = [item.name for item in pool[:count]]
        weight_sets = (
            [1.0] * count,
            [float(value) for value in range(count, 0, -1)],
            [1.0] + [0.75] * (count - 1),
        )
        for weights in weight_sets:
            for k in (0.0, 2.0, 5.0, 10.0):
                candidates.append(score_configuration(arrays, names, weights, k))

    selected_names = [pool[0].name]
    selected_weights = [1.0]
    incumbent_calibration = pool[0].prediction_calibration_map or -1.0
    remaining = [item.name for item in pool[1:]]
    while remaining and len(selected_names) < 5:
        step_candidates: list[dict[str, Any]] = []
        for candidate_name in remaining:
            for candidate_weight in (0.5, 0.75, 1.0, 1.5, 2.0):
                names = [*selected_names, candidate_name]
                weights = [*selected_weights, candidate_weight]
                for k in (0.0, 2.0, 5.0, 10.0):
                    step_candidates.append(
                        score_configuration(arrays, names, weights, k)
                    )
        best_step = max(
            step_candidates,
            key=lambda item: (
                item["calibration_map_at_5"],
                item["evaluation_map_at_5"],
                item["full_map_at_5"],
            ),
        )
        candidates.extend(step_candidates)
        if best_step["calibration_map_at_5"] <= incumbent_calibration + 1e-7:
            break
        selected_names = list(best_step["models"])
        selected_weights = list(best_step["weights"])
        incumbent_calibration = float(best_step["calibration_map_at_5"])
        remaining = [name for name in remaining if name not in selected_names]

    best = max(
        candidates,
        key=lambda item: (
            item["calibration_map_at_5"],
            item["evaluation_map_at_5"],
            item["full_map_at_5"],
            -len(item["models"]),
        ),
    )
    reporter.write(
        "BEST ENSEMBLE: "
        f"cal={best['calibration_map_at_5']:.9f}, "
        f"eval={best['evaluation_map_at_5']:.9f}, "
        f"full={best['full_map_at_5']:.9f}, "
        f"models={best['models']}, weights={best['weights']}, k={best['k']}"
    )

    predictions = rrf_predictions(
        arrays,
        list(best["models"]),
        list(best["weights"]),
        k=float(best["k"]),
    )
    output_path = run_dir / "ensemble_validation_predictions.csv"
    row_ids = arrays["__row_ids__"]
    actual = arrays["__actual__"]
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["row_id", "actual_hotel_cluster", "hotel_cluster"])
        for row_id, cluster, row_predictions in zip(
            row_ids, actual, predictions, strict=True
        ):
            writer.writerow(
                [
                    int(row_id),
                    int(cluster),
                    " ".join(str(int(value)) for value in row_predictions),
                ]
            )

    payload = {
        "best": best,
        "candidate_count": len(candidates),
        "top_candidates": sorted(
            candidates,
            key=lambda item: (
                item["calibration_map_at_5"],
                item["evaluation_map_at_5"],
                item["full_map_at_5"],
            ),
            reverse=True,
        )[:50],
    }
    (run_dir / "ensemble_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return best


def score_model_submission(
    reporter: Reporter,
    run_dir: Path,
    args: argparse.Namespace,
    deadline: float,
    model_run: ModelRun,
) -> tuple[Path | None, CommandResult | None]:
    existing = model_run.directory / "submission_ranker.csv"
    if existing.exists():
        reporter.write(f"Reusing existing test submission for {model_run.name}.")
        return existing, None

    model = model_run.directory / "ranker_model.txt"
    metadata = model_run.directory / "ranker_model_metadata.json"
    if not model.exists() or not metadata.exists():
        reporter.write(f"Cannot score {model_run.name}: model files are missing.")
        return None, None
    remaining = deadline - time.monotonic()
    if remaining < 25 * 60:
        reporter.write(f"Cannot score {model_run.name}: less than 25 minutes remain.")
        return None, None

    copy_if_exists(metadata, ARTIFACTS / "ranker_model_metadata.json")
    result = run_command(
        reporter,
        run_dir,
        f"submit_{model_run.name}",
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
        timeout_seconds=max(60.0, min(50 * 60, remaining - 8 * 60)),
    )
    if result.return_code != 0 or result.timed_out:
        return None, result
    copy_if_exists(ARTIFACTS / "submission_ranker.csv", existing)
    return (existing if existing.exists() else None), result


def build_deep_submissions(
    reporter: Reporter,
    run_dir: Path,
    args: argparse.Namespace,
    deadline: float,
    ranked_models: list[ModelRun],
    selected_single: ModelRun,
    selected_ensemble: dict[str, Any] | None,
) -> tuple[Path | None, dict[str, Any] | None, list[CommandResult]]:
    if args.skip_submission:
        return None, None, []

    models_by_name = {item.name: item for item in ranked_models}
    required_names = (
        list(selected_ensemble["models"])
        if selected_ensemble is not None
        else [selected_single.name]
    )
    targets: list[ModelRun] = []
    for name in required_names:
        model_run = models_by_name[name]
        if model_run not in targets:
            targets.append(model_run)
    for model_run in ranked_models:
        if model_run not in targets:
            targets.append(model_run)

    submissions: dict[str, Path] = {}
    commands: list[CommandResult] = []
    newly_scored = 0
    for model_run in targets:
        has_existing = (model_run.directory / "submission_ranker.csv").exists()
        if not has_existing and newly_scored >= args.max_new_submissions:
            continue
        path, result = score_model_submission(
            reporter,
            run_dir,
            args,
            deadline,
            model_run,
        )
        if result is not None:
            commands.append(result)
            newly_scored += 1
        if path is not None:
            submissions[model_run.name] = path
        if (
            all(name in submissions for name in required_names)
            and newly_scored >= args.max_new_submissions
        ):
            break

    single_path = submissions.get(selected_single.name)
    if single_path is not None:
        copy_if_exists(single_path, ARTIFACTS / "submission_deep_6h_single.csv")

    final_path = ARTIFACTS / "submission_deep_6h_best.csv"
    if selected_ensemble is not None and all(
        name in submissions for name in required_names
    ):
        write_rrf_submission(
            [submissions[name] for name in required_names],
            required_names,
            list(selected_ensemble["weights"]),
            k=float(selected_ensemble["k"]),
            target=final_path,
        )
    elif single_path is not None:
        shutil.copy2(single_path, final_path)
    else:
        reporter.write("No complete final deep submission could be generated.")
        return None, None, commands

    validation = validate_submission(final_path)
    copy_if_exists(final_path, run_dir / "final_submission.csv")
    reporter.write(f"Deep final submission ready: {final_path}")
    return final_path, validation, commands


def main() -> int:
    args = parse_args()
    if args.hours < 5.0 or args.hours > 6.5:
        raise ValueError("hours must be between 5.0 and 6.5 for the deep search")
    if args.threads <= 0 or args.batch_size <= 0 or args.max_new_submissions <= 0:
        raise ValueError("threads, batch-size and max-new-submissions must be positive")

    run_dir = ARTIFACTS / "deep_6h" / utc_stamp()
    run_dir.mkdir(parents=True, exist_ok=False)
    reporter = Reporter(run_dir / "deep_6h.log")
    started = time.monotonic()
    deadline = started + args.hours * 3600
    reserve_submission_seconds = 130 * 60
    commands: list[CommandResult] = []
    model_runs: list[ModelRun] = []
    errors: list[str] = []

    try:
        reporter.write(f"Deep run directory: {run_dir}")
        reporter.write(
            f"Budget={args.hours:.2f}h, threads={args.threads}, "
            f"memory={args.memory_limit}, batch={args.batch_size:,}, "
            f"new test scorings={args.max_new_submissions}"
        )
        validate_environment(reporter)
        hardware = hardware_snapshot()
        (run_dir / "hardware.json").write_text(
            json.dumps(hardware, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reporter.write("Hardware: " + json.dumps(hardware, ensure_ascii=False))

        current_dir = run_dir / "models" / "current_local_model"
        archive_ranker(current_dir)
        model_runs.append(
            ModelRun(
                name="current_local_model",
                directory=current_dir,
                source="existing",
                metrics=load_json(current_dir / "ranker_validation_metrics.json"),
            )
        )
        model_runs.extend(import_previous_candidates(reporter, run_dir))

        for name, command, timeout in (
            ("ruff", ["uv", "run", "ruff", "check", "."], 10 * 60),
            ("pytest", ["uv", "run", "pytest"], 20 * 60),
        ):
            result = run_command(
                reporter,
                run_dir,
                name,
                command,
                timeout_seconds=timeout,
            )
            commands.append(result)
            if result.return_code != 0 or result.timed_out:
                raise RuntimeError(f"Required check failed: {name}. See {result.log_path}")

        training_durations: list[float] = []
        for experiment in EXPERIMENTS:
            remaining = deadline - time.monotonic()
            estimated_training = (
                statistics.median(training_durations) * 1.12
                if training_durations
                else 25 * 60
            )
            if remaining < reserve_submission_seconds + estimated_training + 10 * 60:
                reporter.write(
                    f"Stopping training before {experiment.name}: reserving "
                    "about two hours for five full test scorings and blending."
                )
                break

            experiment_dir = run_dir / "models" / experiment.name
            model_run = ModelRun(
                name=experiment.name,
                directory=experiment_dir,
                source="deep_6h",
                train_start=experiment.train_start,
                max_train_queries=experiment.max_train_queries,
            )
            model_runs.append(model_run)
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
                timeout_seconds=min(
                    100 * 60,
                    max(
                        35 * 60,
                        deadline
                        - time.monotonic()
                        - reserve_submission_seconds
                        - 5 * 60,
                    ),
                ),
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

        successful = [
            item
            for item in model_runs
            if (item.directory / "ranker_validation_predictions.csv").exists()
        ]
        arrays = evaluate_single_predictions(successful, reporter)
        unique_models, unique_arrays = remove_duplicate_predictions(
            successful,
            arrays,
            reporter,
        )
        ensemble = tune_deep_ensemble(
            unique_models,
            unique_arrays,
            reporter,
            run_dir,
        )

        unique_models.sort(
            key=lambda item: (
                item.prediction_evaluation_map or -1.0,
                item.prediction_full_map or -1.0,
                item.prediction_calibration_map or -1.0,
            ),
            reverse=True,
        )
        selected_single = unique_models[0]
        selected_ensemble: dict[str, Any] | None = None
        if ensemble is not None:
            single_eval = selected_single.prediction_evaluation_map or -1.0
            single_full = selected_single.prediction_full_map or -1.0
            if (
                ensemble["evaluation_map_at_5"] > single_eval
                and ensemble["full_map_at_5"] >= single_full
            ):
                selected_ensemble = ensemble
                reporter.write(f"Selected deep ensemble {ensemble['name']}.")
            else:
                reporter.write(
                    "Calibration-selected ensemble failed the independent evaluation gate; "
                    f"using single model {selected_single.name}."
                )

        final_path, submission_validation, submission_commands = build_deep_submissions(
            reporter,
            run_dir,
            args,
            deadline,
            unique_models,
            selected_single,
            selected_ensemble,
        )
        commands.extend(submission_commands)
        restorable_model = next(
            (
                item
                for item in unique_models
                if (item.directory / "ranker_model.txt").exists()
                and (item.directory / "ranker_model_metadata.json").exists()
            ),
            None,
        )
        if restorable_model is not None:
            restore_model(restorable_model)

        elapsed_hours = (time.monotonic() - started) / 3600
        summary = {
            "elapsed_hours": elapsed_hours,
            "configuration": vars(args),
            "hardware": hardware,
            "experiments_planned": [asdict(item) for item in EXPERIMENTS],
            "models": [
                {
                    **asdict(item),
                    "directory": str(item.directory),
                }
                for item in model_runs
            ],
            "unique_model_count": len(unique_models),
            "selected_single": selected_single.name,
            "selected_single_full_map_at_5": selected_single.prediction_full_map,
            "selected_single_evaluation_map_at_5": (
                selected_single.prediction_evaluation_map
            ),
            "selected_ensemble": selected_ensemble,
            "restored_ranker": restorable_model.name if restorable_model else None,
            "final_submission": str(final_path) if final_path else None,
            "submission_validation": submission_validation,
            "commands": [asdict(command) for command in commands],
            "errors": errors,
        }
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        latest_summary = ARTIFACTS / "deep_6h" / "latest_summary.json"
        latest_summary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(summary_path, latest_summary)

        result_lines = [
            "DEEP 6H EXPEDIA SEARCH COMPLETE",
            f"Elapsed: {elapsed_hours:.2f} hours",
            f"Successful unique candidates: {len(unique_models)}",
            f"Best single: {selected_single.name}",
            f"Best single evaluation MAP@5: {selected_single.prediction_evaluation_map:.9f}",
            f"Best single full MAP@5: {selected_single.prediction_full_map:.9f}",
            f"Selected ensemble: {selected_ensemble['name'] if selected_ensemble else 'none'}",
            f"Ensemble evaluation MAP@5: {selected_ensemble['evaluation_map_at_5']:.9f}"
            if selected_ensemble
            else "Ensemble evaluation MAP@5: not selected",
            f"Ensemble full MAP@5: {selected_ensemble['full_map_at_5']:.9f}"
            if selected_ensemble
            else "Ensemble full MAP@5: not selected",
            f"Final submission: {final_path if final_path else 'not generated'}",
            f"Detailed summary: {summary_path}",
        ]
        result_text = "\n".join(result_lines) + "\n"
        (run_dir / "RESULT.txt").write_text(result_text, encoding="utf-8")
        (ARTIFACTS / "deep_6h" / "LATEST_RESULT.txt").write_text(
            result_text,
            encoding="utf-8",
        )
        reporter.write(result_text.replace("\n", " | ").strip(" |"))
        return 0
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        traceback_path = run_dir / "FAILED.txt"
        traceback_path.write_text(traceback.format_exc(), encoding="utf-8")
        reporter.write(f"FAILED: {type(exc).__name__}: {exc}")
        reporter.write(f"Traceback: {traceback_path}")
        return 1


if __name__ == "__main__":
    with prevent_windows_sleep():
        sys.exit(main())
