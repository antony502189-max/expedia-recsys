from __future__ import annotations

import argparse
import os
from pathlib import Path

from expedia_analytics.builder import build_analytics, inspect_analytics, validate_analytics
from expedia_analytics.config import AnalyticsPaths, default_project_root
from expedia_analytics.profiler import profile_sources
from expedia_analytics.source_reconciliation import reconcile_sources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expedia-analytics",
        description="Build reproducible product-analytics marts for Expedia logs.",
    )
    parser.add_argument("--root", type=Path, default=default_project_root())
    parser.add_argument(
        "--threads",
        type=int,
        default=max(1, min(8, os.cpu_count() or 4)),
    )
    parser.add_argument("--memory-limit", default="32GB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "reconcile-sources",
        help="compare raw CSV rows and parse failures with prepared Parquet sources",
    )

    profile = subparsers.add_parser(
        "profile",
        help="profile source schema, nulls, distributions and semantic risks",
    )
    profile.add_argument(
        "--deep",
        action="store_true",
        help="also scan duplicate hashes and strict proxy-search contexts",
    )

    subparsers.add_parser("build", help="build facts, dimensions and marts")
    subparsers.add_parser("validate", help="run reconciliation and quality gates")
    subparsers.add_parser("inspect", help="print the mart registry")
    return parser


def main() -> None:
    args = _parser().parse_args()
    paths = AnalyticsPaths.from_root(args.root)
    if args.command == "reconcile-sources":
        reconcile_sources(
            paths,
            threads=args.threads,
            memory_limit=args.memory_limit,
        )
    elif args.command == "profile":
        profile_sources(
            paths,
            threads=args.threads,
            memory_limit=args.memory_limit,
            deep=args.deep,
        )
    elif args.command == "build":
        build_analytics(
            paths,
            threads=args.threads,
            memory_limit=args.memory_limit,
        )
    elif args.command == "validate":
        validate_analytics(paths)
    elif args.command == "inspect":
        inspect_analytics(paths)
    else:
        raise AssertionError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
