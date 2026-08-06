from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from expedia_recsys.baseline import build_submission, validate_baseline
from expedia_recsys.competition import (
    build_competition_submission,
    validate_competition_candidates,
)
from expedia_recsys.config import ProjectPaths, default_project_root
from expedia_recsys.geo_leak import validate_geo_leak
from expedia_recsys.prepare import prepare_data
from expedia_recsys.ranker_v2 import build_ranker_submission, train_and_validate_ranker


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format") from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expedia-recsys",
        description="Expedia hotel-cluster recommendation pipeline",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_project_root(),
        help="project root containing data/ and artifacts/",
    )
    parser.add_argument(
        "--threads",
        type=_positive_int,
        default=max(1, min(8, os.cpu_count() or 4)),
        help="DuckDB and model worker threads",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit, for example 8GB or 12GB",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="convert Kaggle CSV files to typed Parquet")

    validate = subparsers.add_parser("validate", help="run stage-1 temporal validation")
    validate.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
        help="validation starts at this date",
    )
    subparsers.add_parser("submit", help="build the stage-1 heuristic submission")

    competition_validate = subparsers.add_parser(
        "competition-validate",
        help="validate the 12-source competition candidate generator",
    )
    competition_validate.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
    )
    competition_validate.add_argument(
        "--batch-size",
        type=_positive_int,
        default=25_000,
    )

    competition_submit = subparsers.add_parser(
        "competition-submit",
        help="build the 12-source weighted heuristic submission",
    )
    competition_submit.add_argument(
        "--batch-size",
        type=_positive_int,
        default=25_000,
    )

    ranker_validate = subparsers.add_parser(
        "ranker-validate",
        help="train the MAP@5-aligned blended ranker and score the temporal holdout",
    )
    ranker_validate.add_argument(
        "--train-start",
        type=_iso_date,
        default=date(2014, 1, 1),
    )
    ranker_validate.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
    )
    ranker_validate.add_argument(
        "--max-train-queries",
        type=_positive_int,
        default=100_000,
    )
    ranker_validate.add_argument(
        "--max-eval-queries",
        type=_positive_int,
        default=30_000,
    )
    ranker_validate.add_argument(
        "--batch-size",
        type=_positive_int,
        default=25_000,
    )

    ranker_submit = subparsers.add_parser(
        "ranker-submit",
        help="score the Kaggle test set with the saved blended ranker",
    )
    ranker_submit.add_argument(
        "--model",
        type=Path,
        default=None,
        help="model file; default: artifacts/ranker_model.txt",
    )
    ranker_submit.add_argument(
        "--batch-size",
        type=_positive_int,
        default=25_000,
    )

    geo_validate = subparsers.add_parser(
        "geo-leak-validate",
        help="validate exact and rounded-distance leak overlays on the champion ranker",
    )
    geo_validate.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
    )
    geo_validate.add_argument(
        "--champion",
        type=Path,
        default=None,
        help="champion validation CSV; default: artifacts/ranker_validation_predictions.csv",
    )
    geo_validate.add_argument(
        "--batch-size",
        type=_positive_int,
        default=25_000,
    )

    all_command = subparsers.add_parser("all", help="prepare, validate, and build baseline")
    all_command.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    paths = ProjectPaths.from_root(args.root)
    common = {"threads": args.threads, "memory_limit": args.memory_limit}

    if args.command == "prepare":
        prepare_data(paths, **common)
    elif args.command == "validate":
        validate_baseline(paths, cutoff=args.cutoff, **common)
    elif args.command == "submit":
        build_submission(paths, **common)
    elif args.command == "competition-validate":
        validate_competition_candidates(
            paths,
            cutoff=args.cutoff,
            batch_size=args.batch_size,
            **common,
        )
    elif args.command == "competition-submit":
        build_competition_submission(
            paths,
            batch_size=args.batch_size,
            **common,
        )
    elif args.command == "ranker-validate":
        train_and_validate_ranker(
            paths,
            train_start=args.train_start,
            validation_cutoff=args.cutoff,
            max_train_queries=args.max_train_queries,
            max_eval_queries=args.max_eval_queries,
            batch_size=args.batch_size,
            **common,
        )
    elif args.command == "ranker-submit":
        build_ranker_submission(
            paths,
            model_path=args.model,
            batch_size=args.batch_size,
            **common,
        )
    elif args.command == "geo-leak-validate":
        validate_geo_leak(
            paths,
            cutoff=args.cutoff,
            champion_path=args.champion,
            batch_size=args.batch_size,
            **common,
        )
    elif args.command == "all":
        prepare_data(paths, **common)
        validate_baseline(paths, cutoff=args.cutoff, **common)
        build_submission(paths, **common)
    else:
        raise AssertionError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
