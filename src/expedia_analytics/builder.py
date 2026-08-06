from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.specs import MART_SPECS, MartSpec


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _connect(database_path: Path, *, threads: int, memory_limit: str) -> Any:
    import duckdb

    database_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database_path))
    con.execute(f"SET threads = {max(1, threads)}")
    con.execute(f"SET memory_limit = '{_sql_literal(memory_limit)}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = true")
    temp_dir = database_path.parent / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{_sql_path(temp_dir)}'")
    return con


def _require_sources(paths: AnalyticsPaths) -> None:
    missing = [
        str(path)
        for path in (paths.train_path, paths.destinations_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Missing prepared Parquet sources. Run `uv run expedia-recsys prepare` first:\n"
            + "\n".join(missing)
        )


def _read_sql(paths: AnalyticsPaths, spec: MartSpec) -> str:
    path = paths.sql_dir / spec.sql_file
    if not path.exists():
        raise FileNotFoundError(f"SQL file is missing: {path}")
    return path.read_text(encoding="utf-8").strip().rstrip(";")


def _query_scalar(con: Any, query: str) -> Any:
    row = con.execute(query).fetchone()
    return None if row is None else row[0]


def _create_sources(con: Any, paths: AnalyticsPaths) -> None:
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE SCHEMA analytics")
    con.execute(
        f"""
        CREATE VIEW raw.train_events AS
        SELECT * FROM read_parquet('{_sql_path(paths.train_path)}')
        """
    )
    con.execute(
        f"""
        CREATE VIEW raw.destinations AS
        SELECT * FROM read_parquet('{_sql_path(paths.destinations_path)}')
        """
    )


def _build_table(con: Any, paths: AnalyticsPaths, spec: MartSpec) -> dict[str, Any]:
    sql = _read_sql(paths, spec)
    started = time.monotonic()
    print(f"[analytics] build analytics.{spec.name}")
    con.execute(f"CREATE TABLE analytics.{spec.name} AS\n{sql}")
    row_count = int(_query_scalar(con, f"SELECT COUNT(*) FROM analytics.{spec.name}"))
    if row_count <= 0:
        raise RuntimeError(f"analytics.{spec.name} is empty")

    parquet_path: Path | None = None
    parquet_size = 0
    if spec.export_parquet:
        parquet_path = paths.marts_dir / f"{spec.name}.parquet"
        temporary_path = parquet_path.with_suffix(".parquet.tmp")
        temporary_path.unlink(missing_ok=True)
        con.execute(
            f"""
            COPY analytics.{spec.name}
            TO '{_sql_path(temporary_path)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        os.replace(temporary_path, parquet_path)
        parquet_size = parquet_path.stat().st_size

    min_date = None
    max_date = None
    if spec.date_column:
        min_date, max_date = con.execute(
            f"""
            SELECT MIN({spec.date_column})::VARCHAR, MAX({spec.date_column})::VARCHAR
            FROM analytics.{spec.name}
            """
        ).fetchone()

    elapsed = time.monotonic() - started
    print(
        f"[analytics] complete {spec.name}: rows={row_count:,}, "
        f"elapsed={elapsed / 60:.1f} min"
    )
    return {
        "name": spec.name,
        "grain": spec.grain,
        "description": spec.description,
        "sql_file": spec.sql_file,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "rows": row_count,
        "min_date": min_date,
        "max_date": max_date,
        "parquet_path": str(parquet_path) if parquet_path else None,
        "parquet_bytes": parquet_size,
        "elapsed_seconds": elapsed,
    }


def _quality_checks(con: Any) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, query: str, expected: Any, operator: str = "eq") -> None:
        actual = _query_scalar(con, query)
        passed = {
            "eq": actual == expected,
            "ge": actual >= expected,
            "le": actual <= expected,
        }[operator]
        checks.append(
            {
                "name": name,
                "actual": actual,
                "expected": expected,
                "operator": operator,
                "passed": bool(passed),
            }
        )

    source_rows = int(_query_scalar(con, "SELECT COUNT(*) FROM raw.train_events"))
    add(
        "fact_preserves_source_rows",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions",
        source_rows,
    )
    add(
        "fact_has_no_null_event_dates",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE event_date IS NULL",
        0,
    )
    add(
        "fact_has_valid_booking_flag",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE is_booking NOT IN (0, 1)",
        0,
    )
    add(
        "event_weight_is_positive",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE event_weight < 1",
        0,
    )
    context_rows = int(
        _query_scalar(con, "SELECT COUNT(*) FROM analytics.fct_search_contexts")
    )
    add(
        "daily_context_totals_reconcile",
        "SELECT SUM(search_contexts) FROM analytics.dm_product_daily",
        context_rows,
    )
    booking_contexts = int(
        _query_scalar(
            con,
            "SELECT COUNT(*) FROM analytics.fct_search_contexts WHERE has_booking",
        )
    )
    add(
        "daily_booking_totals_reconcile",
        "SELECT SUM(booking_contexts) FROM analytics.dm_product_daily",
        booking_contexts,
    )
    add(
        "daily_rates_are_bounded",
        """
        SELECT COUNT(*) FROM analytics.dm_product_daily
        WHERE booking_context_rate < 0 OR booking_context_rate > 1
           OR mobile_context_share < 0 OR mobile_context_share > 1
           OR package_context_share < 0 OR package_context_share > 1
        """,
        0,
    )
    add(
        "destination_rates_are_bounded",
        """
        SELECT COUNT(*) FROM analytics.dm_destination_performance
        WHERE booking_context_rate < 0 OR booking_context_rate > 1
        """,
        0,
    )
    failures = [check for check in checks if not check["passed"]]
    return {
        "passed": not failures,
        "checks": checks,
        "failure_count": len(failures),
    }


def _write_registry(con: Any, mart_results: list[dict[str, Any]]) -> None:
    con.execute(
        """
        CREATE TABLE analytics.meta_mart_registry (
            mart_name VARCHAR,
            grain VARCHAR,
            description VARCHAR,
            sql_file VARCHAR,
            row_count BIGINT,
            min_date VARCHAR,
            max_date VARCHAR,
            parquet_path VARCHAR,
            parquet_bytes BIGINT,
            elapsed_seconds DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO analytics.meta_mart_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                item["name"],
                item["grain"],
                item["description"],
                item["sql_file"],
                item["rows"],
                item["min_date"],
                item["max_date"],
                item["parquet_path"],
                item["parquet_bytes"],
                item["elapsed_seconds"],
            )
            for item in mart_results
        ],
    )


def build_analytics(
    paths: AnalyticsPaths,
    *,
    threads: int = 7,
    memory_limit: str = "32GB",
) -> dict[str, Any]:
    """Build all product-analytics facts, dimensions and marts atomically."""
    _require_sources(paths)
    paths.ensure_output_directories()
    free_bytes = shutil.disk_usage(paths.root).free
    if free_bytes < 30 * 1024**3:
        raise RuntimeError("At least 30 GB of free disk space is required")

    build_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    temporary_db = paths.analytics_dir / f"expedia_analytics.{build_id}.building.duckdb"
    temporary_db.unlink(missing_ok=True)
    started_utc = datetime.now(UTC)
    started = time.monotonic()
    mart_results: list[dict[str, Any]] = []

    con = _connect(temporary_db, threads=threads, memory_limit=memory_limit)
    try:
        _create_sources(con, paths)
        for spec in MART_SPECS:
            mart_results.append(_build_table(con, paths, spec))
        quality = _quality_checks(con)
        if not quality["passed"]:
            failures = [
                check["name"] for check in quality["checks"] if not check["passed"]
            ]
            raise RuntimeError("Quality gates failed: " + ", ".join(failures))
        _write_registry(con, mart_results)
        con.execute("ANALYZE")
        con.execute("CHECKPOINT")
    finally:
        con.close()

    os.replace(temporary_db, paths.database_path)
    finished_utc = datetime.now(UTC)
    manifest = {
        "build_id": build_id,
        "status": "success",
        "started_utc": started_utc.isoformat(),
        "finished_utc": finished_utc.isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "configuration": {
            "threads": threads,
            "memory_limit": memory_limit,
        },
        "sources": {
            "train_parquet": str(paths.train_path),
            "train_bytes": paths.train_path.stat().st_size,
            "destinations_parquet": str(paths.destinations_path),
            "destinations_bytes": paths.destinations_path.stat().st_size,
        },
        "database": str(paths.database_path),
        "marts": mart_results,
        "quality": quality,
        "metric_warning": (
            "Search contexts are deterministic proxies because the source has no explicit "
            "session or search_request_id. cnt is used as the number of similar events in "
            "the same user-session context."
        ),
    }
    manifest_path = paths.artifacts_dir / "build_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (paths.marts_dir / "LATEST_BUILD.json").write_text(
        json.dumps(
            {
                "build_id": build_id,
                "database": str(paths.database_path),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[analytics] build complete: {len(mart_results)} marts, "
        f"{manifest['elapsed_seconds'] / 60:.1f} min"
    )
    return manifest


def validate_analytics(paths: AnalyticsPaths) -> dict[str, Any]:
    if not paths.database_path.exists():
        raise FileNotFoundError(
            f"Analytics database is missing: {paths.database_path}. Run build first."
        )
    con = _connect(paths.database_path, threads=2, memory_limit="4GB")
    try:
        result = _quality_checks(con)
    finally:
        con.close()
    report_path = paths.artifacts_dir / "validation_report.json"
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not result["passed"]:
        raise RuntimeError(f"Analytics validation failed. See {report_path}")
    print(f"[analytics] validation passed: {len(result['checks'])} checks")
    return result


def inspect_analytics(paths: AnalyticsPaths) -> list[dict[str, Any]]:
    if not paths.database_path.exists():
        raise FileNotFoundError(
            f"Analytics database is missing: {paths.database_path}. Run build first."
        )
    con = _connect(paths.database_path, threads=2, memory_limit="4GB")
    try:
        rows = con.execute(
            """
            SELECT mart_name, grain, row_count, min_date, max_date, parquet_path
            FROM analytics.meta_mart_registry
            ORDER BY mart_name
            """
        ).fetchall()
        columns = [item[0] for item in con.description]
    finally:
        con.close()
    result = [dict(zip(columns, row, strict=True)) for row in rows]
    for item in result:
        print(
            f"{item['mart_name']:<32} rows={item['row_count']:>12,} "
            f"grain={item['grain']}"
        )
    return result
