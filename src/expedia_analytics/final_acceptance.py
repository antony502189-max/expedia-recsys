from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from expedia_analytics.comparison import compare_builds
from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.final_builder import _json_dumps
from expedia_analytics.final_common import _load_contract


def _load_manifest(paths: AnalyticsPaths, build_id: str) -> dict[str, Any]:
    path = paths.artifacts_dir / build_id / "build_manifest.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _object_rows(manifest: dict[str, Any], name: str) -> int:
    for item in manifest["objects"]:
        if item["name"] == name:
            return int(item["logical_checksum"]["rows"])
    raise KeyError(f"Object is absent from manifest: {name}")


def _source_row_counts(manifest: dict[str, Any]) -> dict[str, int]:
    return {
        "train": _object_rows(manifest, "stg_train_accepted")
        + _object_rows(manifest, "quarantine_train"),
        "test": _object_rows(manifest, "stg_test_accepted")
        + _object_rows(manifest, "quarantine_test"),
        "destinations": _object_rows(manifest, "stg_destinations_accepted")
        + _object_rows(manifest, "quarantine_destinations"),
    }


def _manual_verification(
    path: Path | None,
    *,
    left_build: str,
    right_build: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if path is None or not path.exists():
        checks.append(
            {
                "name": "manual_verification_file_exists",
                "passed": False,
                "actual": str(path) if path else None,
                "expected": "existing reviewed JSON file",
            }
        )
        return None, checks

    # utf-8-sig accepts both plain UTF-8 and Windows-created UTF-8 files with BOM.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    checks.extend(
        [
            {
                "name": "manual_verification_build_pair_matches",
                "passed": payload.get("left_build") == left_build
                and payload.get("right_build") == right_build,
                "actual": [payload.get("left_build"), payload.get("right_build")],
                "expected": [left_build, right_build],
            },
            {
                "name": "representative_rows_verified",
                "passed": payload.get("representative_rows_verified") is True,
                "actual": payload.get("representative_rows_verified"),
                "expected": True,
            },
            {
                "name": "headline_totals_verified",
                "passed": payload.get("headline_totals_verified") is True,
                "actual": payload.get("headline_totals_verified"),
                "expected": True,
            },
            {
                "name": "quarantine_rows_reviewed",
                "passed": payload.get("quarantine_rows_reviewed") is True,
                "actual": payload.get("quarantine_rows_reviewed"),
                "expected": True,
            },
            {
                "name": "reviewer_is_recorded",
                "passed": bool(payload.get("reviewer")),
                "actual": payload.get("reviewer"),
                "expected": "non-empty reviewer",
            },
            {
                "name": "verification_timestamp_is_recorded",
                "passed": bool(payload.get("verified_utc")),
                "actual": payload.get("verified_utc"),
                "expected": "UTC timestamp",
            },
        ]
    )
    return payload, checks


def evaluate_final_acceptance(
    paths: AnalyticsPaths,
    left_build: str,
    right_build: str,
    *,
    manual_verification_path: Path | None = None,
) -> dict[str, Any]:
    """Return the authoritative binary verdict for project artifact one."""
    contract = _load_contract(paths)
    left = _load_manifest(paths, left_build)
    right = _load_manifest(paths, right_build)
    checks: list[dict[str, Any]] = []

    def add(name: str, actual: Any, expected: Any, passed: bool) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "actual": actual,
                "expected": expected,
            }
        )

    for build_id, manifest in ((left_build, left), (right_build, right)):
        add(
            f"{build_id}:status_success",
            manifest.get("status"),
            "success",
            manifest.get("status") == "success",
        )
        add(
            f"{build_id}:quality_passed",
            manifest.get("quality", {}).get("passed"),
            True,
            manifest.get("quality", {}).get("passed") is True,
        )
        add(
            f"{build_id}:clean_git_tree",
            manifest.get("git", {}).get("dirty"),
            False,
            manifest.get("git", {}).get("dirty") is False,
        )
        success_path = paths.artifacts_dir / build_id / "SUCCESS.json"
        add(
            f"{build_id}:success_marker_exists",
            str(success_path),
            "existing SUCCESS.json",
            success_path.exists(),
        )

    add(
        "same_schema_version",
        [left.get("schema_version"), right.get("schema_version")],
        "identical",
        left.get("schema_version") == right.get("schema_version"),
    )
    add(
        "same_contract_hash",
        [left.get("contract_sha256"), right.get("contract_sha256")],
        "identical",
        left.get("contract_sha256") == right.get("contract_sha256"),
    )
    left_sources = {
        name: value.get("sha256") for name, value in left.get("sources", {}).items()
    }
    right_sources = {
        name: value.get("sha256") for name, value in right.get("sources", {}).items()
    }
    add(
        "same_raw_sources",
        [left_sources, right_sources],
        "identical source SHA-256 values",
        left_sources == right_sources,
    )

    minimums = contract["full_dataset_minimums"]
    for build_id, manifest in ((left_build, left), (right_build, right)):
        row_counts = _source_row_counts(manifest)
        for source, minimum in minimums.items():
            actual = row_counts[source]
            add(
                f"{build_id}:{source}_full_dataset_minimum",
                actual,
                f">={minimum}",
                actual >= int(minimum),
            )

    comparison = compare_builds(paths, left_build, right_build, exact=True)
    add(
        "logical_checksums_identical",
        comparison["identical_logical_checksums"],
        True,
        comparison["identical_logical_checksums"] is True,
    )
    add(
        "exact_table_multisets_identical",
        comparison["exact_identical"],
        True,
        comparison["exact_identical"] is True,
    )

    manual, manual_checks = _manual_verification(
        manual_verification_path,
        left_build=left_build,
        right_build=right_build,
    )
    checks.extend(manual_checks)
    failures = [check for check in checks if not check["passed"]]
    report = {
        "verdict": "YES" if not failures else "NO",
        "passed": not failures,
        "left_build": left_build,
        "right_build": right_build,
        "failure_count": len(failures),
        "checks": checks,
        "comparison": comparison,
        "manual_verification": manual,
        "semantic_scope": contract["semantic_scope"],
    }
    output = paths.artifacts_dir / "FINAL_ACCEPTANCE.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_json_dumps(report), encoding="utf-8")
    return report
