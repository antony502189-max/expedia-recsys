from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths

TRAIN_CASTS: dict[str, str] = {
    "date_time": "TIMESTAMP",
    "site_name": "SMALLINT",
    "posa_continent": "SMALLINT",
    "user_location_country": "INTEGER",
    "user_location_region": "INTEGER",
    "user_location_city": "INTEGER",
    "orig_destination_distance": "DOUBLE",
    "user_id": "BIGINT",
    "is_mobile": "TINYINT",
    "is_package": "TINYINT",
    "channel": "SMALLINT",
    "srch_ci": "DATE",
    "srch_co": "DATE",
    "srch_adults_cnt": "SMALLINT",
    "srch_children_cnt": "SMALLINT",
    "srch_rm_cnt": "SMALLINT",
    "srch_destination_id": "INTEGER",
    "srch_destination_type_id": "SMALLINT",
    "is_booking": "TINYINT",
    "cnt": "INTEGER",
    "hotel_continent": "SMALLINT",
    "hotel_country": "INTEGER",
    "hotel_market": "INTEGER",
    "hotel_cluster": "SMALLINT",
}


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "sha256": _file_sha256(path),
    }


def _connect(*, threads: int, memory_limit: str, temp_dir: Path) -> Any:
    import duckdb

    temp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads = {max(1, threads)}")
    escaped_limit = memory_limit.replace("'", "''")
    con.execute(f"SET memory_limit = '{escaped_limit}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = true")
    con.execute(f"SET temp_directory = '{_sql_path(temp_dir)}'")
    return con


def _train_reconciliation(con: Any) -> dict[str, Any]:
    parse_expressions = []
    for column, target_type in TRAIN_CASTS.items():
        parse_expressions.append(
            "COUNT(*) FILTER ("
            f"WHERE {column} IS NOT NULL AND TRY_CAST({column} AS {target_type}) IS NULL"
            f")::BIGINT AS parse_failure__{column}"
        )

    row = con.execute(
        """
        SELECT
            COUNT(*)::BIGINT AS raw_rows,
            COUNT(*) FILTER (
                WHERE TRY_CAST(date_time AS TIMESTAMP) IS NULL
            )::BIGINT AS invalid_date_time_rows,
            COUNT(*) FILTER (
                WHERE TRY_CAST(hotel_cluster AS SMALLINT) NOT BETWEEN 0 AND 99
                   OR TRY_CAST(hotel_cluster AS SMALLINT) IS NULL
            )::BIGINT AS invalid_hotel_cluster_rows,
            COUNT(*) FILTER (
                WHERE TRY_CAST(date_time AS TIMESTAMP) IS NULL
                   OR TRY_CAST(hotel_cluster AS SMALLINT) NOT BETWEEN 0 AND 99
                   OR TRY_CAST(hotel_cluster AS SMALLINT) IS NULL
            )::BIGINT AS rows_rejected_by_recsys_prepare,
        """
        + ",\n".join(parse_expressions)
        + "\nFROM raw_train"
    ).fetchone()
    columns = [item[0] for item in con.description]
    result = dict(zip(columns, row, strict=True))
    result["processed_rows"] = int(
        con.execute("SELECT COUNT(*) FROM processed_train").fetchone()[0]
    )
    result["raw_minus_processed"] = result["raw_rows"] - result["processed_rows"]
    result["prepare_filter_reconciles"] = (
        result["raw_minus_processed"] == result["rows_rejected_by_recsys_prepare"]
    )
    result["all_raw_rows_preserved_in_processed"] = result["raw_minus_processed"] == 0
    return result


def _destination_reconciliation(con: Any) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT
            COUNT(*)::BIGINT AS raw_rows,
            COUNT(*) FILTER (
                WHERE TRY_CAST(srch_destination_id AS INTEGER) IS NULL
            )::BIGINT AS rows_rejected_by_recsys_prepare,
            COUNT(*) FILTER (
                WHERE srch_destination_id IS NOT NULL
                  AND TRY_CAST(srch_destination_id AS INTEGER) IS NULL
            )::BIGINT AS destination_id_parse_failures
        FROM raw_destinations
        """
    ).fetchone()
    columns = [item[0] for item in con.description]
    result = dict(zip(columns, row, strict=True))
    result["processed_rows"] = int(
        con.execute("SELECT COUNT(*) FROM processed_destinations").fetchone()[0]
    )
    result["raw_minus_processed"] = result["raw_rows"] - result["processed_rows"]
    result["prepare_filter_reconciles"] = (
        result["raw_minus_processed"] == result["rows_rejected_by_recsys_prepare"]
    )
    result["all_raw_rows_preserved_in_processed"] = result["raw_minus_processed"] == 0
    return result


def _render_markdown(report: dict[str, Any]) -> str:
    train = report["train"]
    destinations = report["destinations"]
    train_status = "PASS" if train["all_raw_rows_preserved_in_processed"] else "WARNING"
    destination_status = (
        "PASS" if destinations["all_raw_rows_preserved_in_processed"] else "WARNING"
    )
    return "\n".join(
        [
            "# Raw-to-processed source reconciliation",
            "",
            f"Generated UTC: `{report['generated_utc']}`",
            "",
            "## Train",
            "",
            f"- status: **{train_status}**",
            f"- raw rows: **{train['raw_rows']:,}**",
            f"- processed rows: **{train['processed_rows']:,}**",
            f"- raw minus processed: **{train['raw_minus_processed']:,}**",
            f"- rows rejected by current prepare filter: "
            f"**{train['rows_rejected_by_recsys_prepare']:,}**",
            f"- filter reconciliation: **{train['prepare_filter_reconciles']}**",
            "",
            "## Destinations",
            "",
            f"- status: **{destination_status}**",
            f"- raw rows: **{destinations['raw_rows']:,}**",
            f"- processed rows: **{destinations['processed_rows']:,}**",
            f"- raw minus processed: **{destinations['raw_minus_processed']:,}**",
            "",
            "## Interpretation",
            "",
            "The recommendation-oriented preparation layer may filter malformed rows. "
            "A final analytical staging layer must either preserve every raw row or publish "
            "a quarantine table and reconcile it explicitly.",
            "",
        ]
    )


def reconcile_sources(
    paths: AnalyticsPaths,
    *,
    threads: int = 7,
    memory_limit: str = "32GB",
) -> dict[str, Any]:
    """Reconcile raw CSV rows and parse failures against prepared Parquet sources."""
    raw_train = paths.find_raw_train()
    raw_destinations = paths.find_raw_destinations()
    for path in (paths.train_path, paths.destinations_path):
        if not path.exists():
            raise FileNotFoundError(f"Prepared source is missing: {path}")

    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    con = _connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_dir=paths.analytics_dir / "reconciliation_tmp",
    )
    try:
        con.execute(
            f"""
            CREATE VIEW raw_train AS
            SELECT * FROM read_csv(
                '{_sql_path(raw_train)}',
                header = true,
                all_varchar = true,
                nullstr = ''
            )
            """
        )
        con.execute(
            f"""
            CREATE VIEW raw_destinations AS
            SELECT * FROM read_csv(
                '{_sql_path(raw_destinations)}',
                header = true,
                all_varchar = true,
                nullstr = ''
            )
            """
        )
        con.execute(
            "CREATE VIEW processed_train AS "
            f"SELECT * FROM read_parquet('{_sql_path(paths.train_path)}')"
        )
        con.execute(
            "CREATE VIEW processed_destinations AS "
            f"SELECT * FROM read_parquet('{_sql_path(paths.destinations_path)}')"
        )
        report = {
            "generated_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": None,
            "sources": {
                "raw_train": _source_metadata(raw_train),
                "processed_train": _source_metadata(paths.train_path),
                "raw_destinations": _source_metadata(raw_destinations),
                "processed_destinations": _source_metadata(paths.destinations_path),
            },
            "train": _train_reconciliation(con),
            "destinations": _destination_reconciliation(con),
        }
    finally:
        con.close()

    report["elapsed_seconds"] = time.monotonic() - started
    json_path = paths.artifacts_dir / "source_reconciliation.json"
    markdown_path = paths.artifacts_dir / "source_reconciliation.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"[analytics] source reconciliation: {json_path}")
    print(f"[analytics] source reconciliation summary: {markdown_path}")
    return report
