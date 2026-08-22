# ruff: noqa: E501
"""Create and verify the clean Stage 2 Dashboard BI handoff folder and ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from expedia_analytics.bi_dashboard import SOURCE_BUILD_ID

PACKAGE_NAME = "stage2_dashboard_bi"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_readme(target: Path) -> None:
    target.write_text(
        """# Stage 2 Dashboard BI — Start Here

This is the complete, validated DataLens handoff package for Expedia Product
Analytics Stage 2. Upload or connect **the Parquet files in `DATA/`**; use no
Stage 1 mart directly.

## Dashboard datasets

- Page 1: `bi_overview_monthly`
- Page 2: `bi_segments_monthly`, `bi_booking_window`,
  `bi_traveller_planning_monthly`, `bi_checkin_seasonality`
- Page 3: `bi_destination_performance`, `bi_hotel_market_performance`,
  `bi_destination_monthly`, `bi_routes`
- Page 4: `bi_observed_recurrence`
- Page 5: `bi_acceptance_status`, `bi_missingness_daily`,
  `bi_proxy_ambiguity`, `bi_booking_population_drift_summary`

## Essential rules

Calculate the primary outcome as:

`SUM(booking_rows) / SUM(interaction_rows)`

Never use `AVG(booking_interaction_share)`. Keep the numerator and denominator
when filtering. `event_month` is observed activity time, `checkin_month` is
planned check-in time, and `cohort_month` is first-observed cohort time; never
combine them into a generic month field. Support levels are low (<100),
adequate (100–999), and strong (>=1000) interaction rows.

The exact Dashboard contract is in `DASHBOARD_SPEC/`; field meanings and safe
aggregation are in `DATA_DICTIONARY/`; validation values and the visual registry
are in `VALIDATION/`.
""",
        encoding="utf-8",
    )


def _git_sha(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def build_package(root: Path, *, build_id: str = SOURCE_BUILD_ID) -> dict[str, Any]:
    root = root.resolve()
    source_bi = root / "data" / "bi" / build_id
    audit = root / "artifacts" / "dashboard" / "final_bi_audit.json"
    if json.loads(audit.read_text(encoding="utf-8"))["overall_status"] != "passed":
        raise RuntimeError("Final BI audit did not pass; refusing to package delivery")
    destination = root / "deliverables" / PACKAGE_NAME
    archive = root / "deliverables" / f"{PACKAGE_NAME}.zip"
    if destination.exists() or archive.exists():
        raise FileExistsError(f"Refusing to overwrite existing delivery target: {destination}")
    manifest = json.loads((source_bi / "manifest.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True)
    data_dir = destination / "DATA"
    for item in manifest["marts"]:
        _copy(source_bi / f"{item['name']}.parquet", data_dir / f"{item['name']}.parquet")
    _copy(source_bi / "manifest.json", data_dir / "manifest.json")
    groups = {
        "DASHBOARD_SPEC": [
            "stage2_dashboard_spec.md",
            "stage2_dashboard_mart_mapping.md",
            "stage2_kpi_dictionary.md",
        ],
        "DATA_DICTIONARY": [
            "canonical_field_dictionary.md",
            "bi_field_migration_map.md",
            "bi_dashboard_marts.md",
        ],
        "VALIDATION": ["stage2_final_bi_audit.md"],
    }
    for folder, files in groups.items():
        for file_name in files:
            _copy(root / "docs" / file_name, destination / folder / file_name)
    for file_name in (
        "dashboard_validation.json",
        "final_bi_audit.json",
        "visual_coverage_registry.md",
    ):
        _copy(root / "artifacts" / "dashboard" / file_name, destination / "VALIDATION" / file_name)
    _copy(
        root / "artifacts" / "dashboard" / "stage2_analysis_preview.md",
        destination / "ANALYSIS" / "stage2_analysis_preview.md",
    )
    _write_readme(destination / "README_START_HERE.md")
    (destination / "METADATA").mkdir()
    (destination / "METADATA" / "BI_CONTRACT_VERSION.txt").write_text(
        manifest["bi_contract_version"] + "\n", encoding="utf-8"
    )
    (destination / "METADATA" / "BUILD_INFO.md").write_text(
        f"# Build Information\n\n- Source build: `{build_id}`\n- BI contract: `{manifest['bi_contract_version']}`\n- Git SHA: `{_git_sha(root)}`\n- Final audit: PASS\n",
        encoding="utf-8",
    )
    datasets = []
    for item in manifest["marts"]:
        path = data_dir / f"{item['name']}.parquet"
        datasets.append(
            {
                "name": item["name"],
                "file": f"DATA/{path.name}",
                "dashboard_page": item["dashboard_page"],
                "visual_ids": item["dashboard_visuals"],
                "grain": item["grain"],
                "rows": item["row_count"],
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    delivery_manifest = {
        "package_name": PACKAGE_NAME,
        "created_at": datetime.now(UTC).isoformat(),
        "source_build_id": build_id,
        "git_sha": _git_sha(root),
        "bi_contract_version": manifest["bi_contract_version"],
        "audit_status": "passed",
        "dashboard": {"pages": 5, "visuals": 25, "visuals_passed": 25},
        "datasets": datasets,
    }
    (destination / "DELIVERY_MANIFEST.json").write_text(
        json.dumps(delivery_manifest, indent=2) + "\n", encoding="utf-8"
    )
    checksums = []
    for path in sorted(file for file in destination.rglob("*") if file.is_file()):
        if path.name != "FILE_CHECKSUMS.sha256":
            checksums.append(f"{_sha256(path)}  {path.relative_to(destination).as_posix()}")
    (destination / "METADATA" / "FILE_CHECKSUMS.sha256").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    verify_package(destination, manifest, delivery_manifest)
    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zip_file:
        for path in sorted(file for file in destination.rglob("*") if file.is_file()):
            zip_file.write(
                path, arcname=f"{PACKAGE_NAME}/{path.relative_to(destination).as_posix()}"
            )
    with zipfile.ZipFile(archive) as zip_file:
        names = zip_file.namelist()
        if not names or any(not name.startswith(f"{PACKAGE_NAME}/") for name in names):
            raise RuntimeError("ZIP contains files outside the delivery root")
    return {
        "folder": str(destination),
        "zip": str(archive),
        "datasets": len(datasets),
        "status": "passed",
    }


def verify_package(
    destination: Path, source_manifest: dict[str, Any], delivery_manifest: dict[str, Any]
) -> None:
    expected_docs = {
        "README_START_HERE.md",
        "DELIVERY_MANIFEST.json",
        "DATA/manifest.json",
        "DASHBOARD_SPEC/stage2_dashboard_spec.md",
        "DASHBOARD_SPEC/stage2_dashboard_mart_mapping.md",
        "DASHBOARD_SPEC/stage2_kpi_dictionary.md",
        "DATA_DICTIONARY/canonical_field_dictionary.md",
        "DATA_DICTIONARY/bi_field_migration_map.md",
        "DATA_DICTIONARY/bi_dashboard_marts.md",
        "VALIDATION/dashboard_validation.json",
        "VALIDATION/final_bi_audit.json",
        "VALIDATION/stage2_final_bi_audit.md",
        "VALIDATION/visual_coverage_registry.md",
        "ANALYSIS/stage2_analysis_preview.md",
        "METADATA/BUILD_INFO.md",
        "METADATA/BI_CONTRACT_VERSION.txt",
        "METADATA/FILE_CHECKSUMS.sha256",
    }
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if not expected_docs <= actual:
        raise RuntimeError(f"Delivery docs are incomplete: {sorted(expected_docs - actual)}")
    copied_source_manifest = json.loads(
        (destination / "DATA" / "manifest.json").read_text(encoding="utf-8")
    )
    if len(delivery_manifest["datasets"]) != len(source_manifest["marts"]):
        raise RuntimeError("Delivery manifest does not list every dataset")
    con = duckdb.connect()
    try:
        if delivery_manifest.get("data_format") == "csv":
            delivery_by_name = {item["name"]: item for item in delivery_manifest["datasets"]}
            csv_by_name = {item["name"]: item for item in copied_source_manifest["marts"]}
            for item in source_manifest["marts"]:
                delivery = delivery_by_name[item["name"]]
                csv = csv_by_name[item["name"]]
                path = destination / delivery["file"]
                row_count = con.execute(
                    "SELECT COUNT(*) FROM read_csv_auto(?, HEADER=TRUE)", [str(path)]
                ).fetchone()[0]
                columns = [
                    row[0]
                    for row in con.execute(
                        "DESCRIBE SELECT * FROM read_csv_auto(?, HEADER=TRUE)", [str(path)]
                    ).fetchall()
                ]
                expected_rows = csv["row_count"]
                if csv.get("source_row_count", expected_rows) != item["row_count"]:
                    raise RuntimeError(f"Delivery CSV source row count is invalid: {item['name']}")
                if csv.get("delivery_scope", "full") == "full" and expected_rows != item["row_count"]:
                    raise RuntimeError(f"Full delivery CSV was unexpectedly truncated: {item['name']}")
                if item["name"] == "bi_routes":
                    if csv.get("delivery_scope") != "support_level = strong":
                        raise RuntimeError("Routes delivery must be the documented strong-support export")
                    route_supports = con.execute(
                        "SELECT COUNT(*), COUNT(*) FILTER (WHERE support_level = 'strong') "
                        "FROM read_csv_auto(?, HEADER=TRUE)",
                        [str(path)],
                    ).fetchone()
                    if route_supports[0] != route_supports[1]:
                        raise RuntimeError("Routes delivery contains non-strong support rows")
                if (
                    delivery.get("format") != "csv"
                    or row_count != expected_rows
                    or delivery.get("rows") != expected_rows
                    or columns != [column["name"] for column in item["columns"]]
                    or _sha256(path) != delivery["sha256"]
                    or _sha256(path) != csv["delivery_checksum"]
                ):
                    raise RuntimeError(f"Delivery CSV verification failed: {item['name']}")
        else:
            for item in source_manifest["marts"]:
                path = destination / "DATA" / f"{item['name']}.parquet"
                row_count = con.execute(
                    "SELECT COUNT(*) FROM read_parquet(?)", [str(path)]
                ).fetchone()[0]
                schema = [
                    (row[0], row[1])
                    for row in con.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
                    ).fetchall()
                ]
                expected_schema = [(column["name"], column["type"]) for column in item["columns"]]
                if (
                    row_count != item["row_count"]
                    or _sha256(path) != item["checksum"]
                    or schema != expected_schema
                ):
                    raise RuntimeError(f"Delivery Parquet verification failed: {item['name']}")
            if copied_source_manifest != source_manifest:
                raise RuntimeError("Copied BI manifest differs from the audited source manifest")
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-id", default=SOURCE_BUILD_ID)
    parser.add_argument("--verify", action="store_true", help="Verify an existing delivery folder.")
    args = parser.parse_args()
    if args.verify:
        destination = args.root / "deliverables" / PACKAGE_NAME
        source_manifest = json.loads(
            (args.root / "data" / "bi" / args.build_id / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        delivery_manifest = json.loads(
            (destination / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8")
        )
        verify_package(destination, source_manifest, delivery_manifest)
        print(json.dumps({"folder": str(destination), "status": "passed"}, indent=2))
        return 0
    print(json.dumps(build_package(args.root, build_id=args.build_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
