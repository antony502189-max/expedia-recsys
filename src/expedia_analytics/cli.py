from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from expedia_analytics.config import AnalyticsPaths, default_project_root
from expedia_analytics.final_acceptance import evaluate_final_acceptance
from expedia_analytics.final_builder import (
    build_final_analytics,
    compare_builds,
    inspect_latest,
    validate_latest,
)
from expedia_analytics.profiler import profile_sources
from expedia_analytics.source_reconciliation import reconcile_sources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expedia-analytics",
        description="Build the final reproducible Expedia product-analytics data product.",
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
        help="compare raw CSV and legacy prepared Parquet sources",
    )
    profile = subparsers.add_parser(
        "profile",
        help="profile prepared sources before the final full build",
    )
    profile.add_argument("--deep", action="store_true")

    build = subparsers.add_parser(
        "build-final",
        help="build immutable staging, facts, dimensions and marts from raw CSV",
    )
    build.add_argument("--build-id")

    subparsers.add_parser("validate-final", help="validate the latest successful build")
    subparsers.add_parser("inspect-final", help="print the latest build registry")

    compare = subparsers.add_parser(
        "compare-builds",
        help="compare logical checksums from two immutable builds",
    )
    compare.add_argument("left_build")
    compare.add_argument("right_build")
    compare.add_argument(
        "--exact",
        action="store_true",
        help="also run exact EXCEPT ALL comparison across both DuckDB builds",
    )

    acceptance = subparsers.add_parser(
        "acceptance-status",
        help="calculate the authoritative YES/NO verdict for artifact one",
    )
    acceptance.add_argument("left_build")
    acceptance.add_argument("right_build")
    acceptance.add_argument(
        "--manual-verification",
        type=Path,
        required=True,
        help="reviewed JSON based on config/manual_verification.example.json",
    )
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
    elif args.command == "build-final":
        manifest = build_final_analytics(
            paths,
            threads=args.threads,
            memory_limit=args.memory_limit,
            build_id=args.build_id,
        )
        print(
            json.dumps(
                {
                    "build_id": manifest["build_id"],
                    "objects": len(manifest["objects"]),
                    "quality_passed": manifest["quality"]["passed"],
                    "elapsed_seconds": manifest["elapsed_seconds"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "validate-final":
        result = validate_latest(paths)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "inspect-final":
        for item in inspect_latest(paths):
            print(
                f"{item['layer']:<10} {item['name']:<42} "
                f"rows={item['rows']:>12,} bytes={item['bytes']:>14,}"
            )
    elif args.command == "compare-builds":
        result = compare_builds(
            paths,
            args.left_build,
            args.right_build,
            exact=args.exact,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["identical_logical_checksums"]:
            raise SystemExit(1)
        if args.exact and not result["exact_identical"]:
            raise SystemExit(1)
    elif args.command == "acceptance-status":
        result = evaluate_final_acceptance(
            paths,
            args.left_build,
            args.right_build,
            manual_verification_path=args.manual_verification,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["passed"]:
            raise SystemExit(1)
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    main()
