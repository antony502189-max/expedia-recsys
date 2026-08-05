from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from expedia_recsys.baseline import build_submission, validate_baseline
from expedia_recsys.config import ProjectPaths, default_project_root
from expedia_recsys.prepare import prepare_data


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expedia-recsys",
        description="Stage 1 Expedia recommendation pipeline",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_project_root(),
        help="project root containing data/ and artifacts/",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=max(1, min(8, os.cpu_count() or 4)),
        help="DuckDB worker threads",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit, for example 8GB or 12GB",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="convert Kaggle CSV files to typed Parquet")

    validate = subparsers.add_parser("validate", help="run temporal validation and MAP@5")
    validate.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
        help="validation starts at this date; default: 2014-08-01",
    )

    subparsers.add_parser("submit", help="train on all history and build test submission")

    all_command = subparsers.add_parser("all", help="prepare, validate, and build submission")
    all_command.add_argument(
        "--cutoff",
        type=_iso_date,
        default=date(2014, 8, 1),
        help="validation starts at this date; default: 2014-08-01",
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
    elif args.command == "all":
        prepare_data(paths, **common)
        validate_baseline(paths, cutoff=args.cutoff, **common)
        build_submission(paths, **common)
    else:
        raise AssertionError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
