from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import PUBLISHED_OBJECTS
from expedia_analytics.final_common import (
    _connect,
    _git_metadata,
    _load_contract,
    _sha256_file,
    _sql_path,
)
from expedia_analytics.final_core import _create_core, _create_dimensions
from expedia_analytics.final_marts import _create_marts
from expedia_analytics.final_staging import _create_raw_landings, _create_staging
from expedia_analytics.final_validation import (
    _copy_table,
    _logical_checksum,
    _publish_pointer,
    _quality_gates,
)


class BuildValidationError(RuntimeError):
    pass


def build_final_analytics(
    paths: AnalyticsPaths,
    *,
    threads: int = 7,
    memory_limit: str = "32GB",
    build_id: str | None = None,
) -> dict[str, Any]:
    """Build the versioned, row-reconciled product-analytics data product."""
    paths.ensure_base_directories()
    contract = _load_contract(paths)
    git = _git_metadata(paths.root)
    started_utc = datetime.now(UTC)
    build_id = build_id or started_utc.strftime("%Y%m%dT%H%M%SZ")
    final_database_dir = paths.analytics_dir / build_id
    final_marts_dir = paths.marts_dir / build_id
    final_artifacts_dir = paths.artifacts_dir / build_id
    if any(path.exists() for path in (final_database_dir, final_marts_dir, final_artifacts_dir)):
        raise FileExistsError(f"Build ID already exists: {build_id}")

    working_root = paths.artifacts_dir / f".{build_id}.building"
    database_work = working_root / "database" / "expedia_analytics.duckdb"
    marts_work = working_root / "marts"
    artifacts_work = working_root / "artifacts"
    temp_dir = working_root / "duckdb_tmp"
    working_root.mkdir(parents=True, exist_ok=False)
    marts_work.mkdir(parents=True)
    artifacts_work.mkdir(parents=True)

    started = time.monotonic()
    con = _connect(
        database_work,
        threads=threads,
        memory_limit=memory_limit,
        temp_dir=temp_dir,
    )
    try:
        sources = _create_raw_landings(con, paths)
        _create_staging(con)
        _create_core(con, contract)
        _create_dimensions(con)
        _create_marts(con, contract)
        quality = _quality_gates(con, contract)
        if not quality["passed"]:
            failures = [item["name"] for item in quality["checks"] if not item["passed"]]
            raise BuildValidationError("Quality gates failed: " + ", ".join(failures))

        objects: list[dict[str, Any]] = []
        for spec in PUBLISHED_OBJECTS:
            checksum = _logical_checksum(con, spec)
            export = _copy_table(con, spec=spec, target_root=marts_work)
            objects.append(
                {
                    **asdict(spec),
                    "logical_checksum": checksum,
                    "export": export,
                }
            )
        con.execute("ANALYZE")
        con.execute("CHECKPOINT")
        runtime = {
            "python": sys.version,
            "platform": platform.platform(),
            "duckdb": con.execute("SELECT version()").fetchone()[0],
        }
    finally:
        con.close()

    database_sha256 = _sha256_file(database_work)
    source_manifest = {
        name: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
            "sha256": _sha256_file(path),
        }
        for name, path in sources.items()
    }
    manifest = {
        "schema_version": contract["schema_version"],
        "build_id": build_id,
        "status": "success",
        "started_utc": started_utc.isoformat(),
        "finished_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "configuration": {"threads": threads, "memory_limit": memory_limit},
        "git": git,
        "runtime": runtime,
        "contract_sha256": _sha256_file(paths.contract_path),
        "uv_lock_sha256": (
            _sha256_file(paths.root / "uv.lock") if (paths.root / "uv.lock").exists() else None
        ),
        "sources": source_manifest,
        "database_sha256": database_sha256,
        "objects": objects,
        "quality": quality,
        "semantic_scope": contract["semantic_scope"],
        "prohibited_claims": contract["prohibited_claims"],
    }
    (artifacts_work / "build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifacts_work / "validation_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifacts_work / "analytics_contract_snapshot.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifacts_work / "SUCCESS.json").write_text(
        json.dumps(
            {
                "build_id": build_id,
                "schema_version": contract["schema_version"],
                "quality_passed": True,
                "database_sha256": database_sha256,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    final_database_dir.parent.mkdir(parents=True, exist_ok=True)
    final_marts_dir.parent.mkdir(parents=True, exist_ok=True)
    final_artifacts_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(database_work.parent, final_database_dir)
    os.replace(marts_work, final_marts_dir)
    os.replace(artifacts_work, final_artifacts_dir)
    shutil.rmtree(working_root, ignore_errors=True)

    pointer = {
        "build_id": build_id,
        "schema_version": contract["schema_version"],
        "database": str(final_database_dir / "expedia_analytics.duckdb"),
        "marts": str(final_marts_dir),
        "artifacts": str(final_artifacts_dir),
        "manifest": str(final_artifacts_dir / "build_manifest.json"),
    }
    _publish_pointer(paths, pointer)
    return manifest


def validate_latest(paths: AnalyticsPaths) -> dict[str, Any]:
    contract = _load_contract(paths)
    database = paths.resolve_latest_database()
    con = _connect(
        database,
        threads=2,
        memory_limit="4GB",
        temp_dir=paths.analytics_dir / "validation_tmp",
    )
    try:
        quality = _quality_gates(con, contract)
    finally:
        con.close()
    if not quality["passed"]:
        failures = [item["name"] for item in quality["checks"] if not item["passed"]]
        raise BuildValidationError("Latest build is invalid: " + ", ".join(failures))
    return quality


def inspect_latest(paths: AnalyticsPaths) -> list[dict[str, Any]]:
    pointer = json.loads(paths.latest_pointer_path.read_text(encoding="utf-8"))
    manifest_path = Path(pointer["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = paths.root / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = []
    for item in manifest["objects"]:
        result.append(
            {
                "name": item["name"],
                "layer": item["layer"],
                "grain": item["grain"],
                "rows": item["logical_checksum"]["rows"],
                "bytes": item["export"]["bytes"],
            }
        )
    return result


def compare_builds(
    paths: AnalyticsPaths,
    left_build: str,
    right_build: str,
    *,
    exact: bool = False,
) -> dict[str, Any]:
    def load(build_id: str) -> dict[str, Any]:
        path = paths.artifacts_dir / build_id / "build_manifest.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    left = load(left_build)
    right = load(right_build)
    left_objects = {item["name"]: item for item in left["objects"]}
    right_objects = {item["name"]: item for item in right["objects"]}
    names = sorted(set(left_objects) | set(right_objects))
    rows: list[dict[str, Any]] = []
    identical = True
    for name in names:
        left_object = left_objects.get(name)
        right_object = right_objects.get(name)
        left_checksum = left_object and left_object["logical_checksum"]
        right_checksum = right_object and right_object["logical_checksum"]
        same = left_checksum == right_checksum
        identical = identical and same
        rows.append(
            {
                "object": name,
                "identical": same,
                "left": left_checksum,
                "right": right_checksum,
            }
        )

    exact_rows: list[dict[str, Any]] | None = None
    exact_identical: bool | None = None
    if exact:
        import duckdb

        left_database = paths.analytics_dir / left_build / "expedia_analytics.duckdb"
        right_database = paths.analytics_dir / right_build / "expedia_analytics.duckdb"
        for path in (left_database, right_database):
            if not path.exists():
                raise FileNotFoundError(path)
        con = duckdb.connect()
        try:
            con.execute(
                f"ATTACH '{_sql_path(left_database)}' AS left_build (READ_ONLY)"
            )
            con.execute(
                f"ATTACH '{_sql_path(right_database)}' AS right_build (READ_ONLY)"
            )
            exact_rows = []
            exact_identical = True
            for spec in PUBLISHED_OBJECTS:
                schema = "staging" if spec.layer == "staging" else "analytics"
                left_relation = f"left_build.{schema}.{spec.name}"
                right_relation = f"right_build.{schema}.{spec.name}"
                left_schema = con.execute(
                    f"DESCRIBE SELECT * FROM {left_relation}"
                ).fetchall()
                right_schema = con.execute(
                    f"DESCRIBE SELECT * FROM {right_relation}"
                ).fetchall()
                schemas_match = left_schema == right_schema
                difference_rows = None
                if schemas_match:
                    difference_rows = int(
                        con.execute(
                            f"""
                            SELECT COUNT(*) FROM (
                                (SELECT * FROM {left_relation}
                                 EXCEPT ALL
                                 SELECT * FROM {right_relation})
                                UNION ALL
                                (SELECT * FROM {right_relation}
                                 EXCEPT ALL
                                 SELECT * FROM {left_relation})
                            ) differences
                            """
                        ).fetchone()[0]
                    )
                same = schemas_match and difference_rows == 0
                exact_identical = exact_identical and same
                exact_rows.append(
                    {
                        "object": spec.name,
                        "schemas_match": schemas_match,
                        "symmetric_difference_rows": difference_rows,
                        "identical": same,
                    }
                )
        finally:
            con.close()

    return {
        "left_build": left_build,
        "right_build": right_build,
        "identical_logical_checksums": identical,
        "objects": rows,
        "exact_requested": exact,
        "exact_identical": exact_identical,
        "exact_objects": exact_rows,
    }
