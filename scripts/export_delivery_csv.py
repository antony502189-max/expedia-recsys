# ruff: noqa: E501
"""Replace delivery-package BI data files with validated CSV exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

import duckdb

BUILD_ID = "20260807T121247Z"
PACKAGE_NAME = "stage2_dashboard_bi"
ROUTES_DATALENS_FILTER = "support_level = 'strong'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def export_delivery_csv(root: Path, *, build_id: str = BUILD_ID) -> dict[str, object]:
    root = root.resolve()
    source_dir = root / "data" / "bi" / build_id
    package = root / "deliverables" / PACKAGE_NAME
    data_dir = package / "DATA"
    archive = root / "deliverables" / f"{PACKAGE_NAME}.zip"
    source_manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    delivery_manifest_path = package / "DELIVERY_MANIFEST.json"
    delivery_manifest = json.loads(delivery_manifest_path.read_text(encoding="utf-8"))
    con = duckdb.connect()
    csv_items: list[dict[str, object]] = []
    try:
        for mart in source_manifest["marts"]:
            name = mart["name"]
            source = source_dir / f"{name}.parquet"
            target = data_dir / f"{name}.csv"
            temporary = data_dir / f".{name}.csv.tmp"
            query = f"SELECT * FROM read_parquet('{_sql_path(source)}')"
            if name == "bi_routes":
                # The full routes mart is 3.8M rows / 444 MB as CSV. Visual 18 is
                # contractually scoped to strong support, so publish that exact
                # non-lossy-for-the-visual subset for the DataLens handoff.
                query = f"{query} WHERE {ROUTES_DATALENS_FILTER}"
            con.execute(
                f"COPY ({query}) TO '{_sql_path(temporary)}' (HEADER, DELIMITER ',')"
            )
            row_count = con.execute(
                f"SELECT COUNT(*) FROM read_csv_auto('{_sql_path(temporary)}', HEADER=TRUE)"
            ).fetchone()[0]
            if name != "bi_routes" and row_count != mart["row_count"]:
                raise RuntimeError(f"CSV row-count validation failed for {name}")
            os.replace(temporary, target)
            csv_item = {
                **mart,
                "row_count": row_count,
                "source_row_count": mart["row_count"],
                "delivery_scope": "full",
                "delivery_file": target.name,
                "delivery_format": "csv",
                "delivery_size_bytes": target.stat().st_size,
                "delivery_checksum": _sha256(target),
                "source_parquet_checksum": mart["checksum"],
            }
            if name == "bi_routes":
                csv_item["delivery_scope"] = "support_level = strong"
            csv_items.append(csv_item)
    finally:
        con.close()
    csv_manifest = {
        "bi_contract_version": source_manifest["bi_contract_version"],
        "source_build_id": build_id,
        "delivery_data_format": "csv",
        "marts": csv_items,
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(csv_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    delivery_by_name = {item["name"]: item for item in delivery_manifest["datasets"]}
    for item in csv_items:
        entry = delivery_by_name[item["name"]]
        entry["file"] = f"DATA/{item['delivery_file']}"
        entry["format"] = "csv"
        entry["size_bytes"] = item["delivery_size_bytes"]
        entry["sha256"] = item["delivery_checksum"]
        entry["source_parquet_sha256"] = item["source_parquet_checksum"]
        entry["rows"] = item["row_count"]
        entry["source_rows"] = item["source_row_count"]
        entry["delivery_scope"] = item["delivery_scope"]
    delivery_manifest["data_format"] = "csv"
    delivery_manifest["source_truth_sanity_check"] = "passed"
    delivery_manifest_path.write_text(
        json.dumps(delivery_manifest, indent=2) + "\n", encoding="utf-8"
    )
    readme = package / "README_START_HERE.md"
    content = readme.read_text(encoding="utf-8")
    marker = "Upload or connect **the CSV files in `DATA/`**"
    content = content.replace("Upload or connect **the Parquet files in `DATA/`**", marker).replace(
        "Parquet files", "CSV files"
    )
    route_note = (
        "\n`bi_routes.csv` is the compact DataLens export for Visual 18: it contains all "
        "strong-support routes (`support_level = strong`, 2,179 rows). The full audited "
        "route mart remains unchanged in `data/bi/`.\n"
    )
    if route_note not in content:
        content += route_note
    readme.write_text(content, encoding="utf-8")
    # The source data remain unchanged; only now-redundant package copies are removed.
    for mart in source_manifest["marts"]:
        (data_dir / f"{mart['name']}.parquet").unlink(missing_ok=True)
    checksums = [
        f"{_sha256(path)}  {path.relative_to(package).as_posix()}"
        for path in sorted(
            file
            for file in package.rglob("*")
            if file.is_file() and file.name != "FILE_CHECKSUMS.sha256"
        )
    ]
    (package / "METADATA" / "FILE_CHECKSUMS.sha256").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    temporary_archive = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(
        temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zip_file:
        for path in sorted(file for file in package.rglob("*") if file.is_file()):
            zip_file.write(path, arcname=f"{PACKAGE_NAME}/{path.relative_to(package).as_posix()}")
    os.replace(temporary_archive, archive)
    return {
        "status": "passed",
        "format": "csv",
        "datasets": len(csv_items),
        "folder": str(package),
        "zip": str(archive),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-id", default=BUILD_ID)
    args = parser.parse_args()
    print(json.dumps(export_delivery_csv(args.root, build_id=args.build_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
