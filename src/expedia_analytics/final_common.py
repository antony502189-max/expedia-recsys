from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import ColumnSpec


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_metadata(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status) if status is not None else None,
    }


def _connect(database: Path, *, threads: int, memory_limit: str, temp_dir: Path) -> Any:
    import duckdb

    database.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database))
    con.execute(f"SET threads = {max(1, threads)}")
    con.execute(f"SET memory_limit = '{_sql_literal(memory_limit)}'")
    con.execute("SET preserve_insertion_order = true")
    con.execute("SET enable_progress_bar = true")
    con.execute(f"SET temp_directory = '{_sql_path(temp_dir)}'")
    return con


def _load_contract(paths: AnalyticsPaths) -> dict[str, Any]:
    if not paths.contract_path.exists():
        raise FileNotFoundError(f"Analytics contract is missing: {paths.contract_path}")
    payload = json.loads(paths.contract_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "segment_boundaries",
        "support_thresholds",
        "quality_thresholds",
        "published_metric_names",
        "prohibited_claims",
        "full_dataset_minimums",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError("Analytics contract is missing keys: " + ", ".join(missing))
    return payload


def _read_csv_relation(path: Path) -> str:
    return (
        "read_csv("
        f"'{_sql_path(path)}', header=true, all_varchar=true, nullstr='', "
        "ignore_errors=false, parallel=false, filename=true)"
    )


def _raw_expr(name: str) -> str:
    return f'NULLIF(TRIM("{name}"), \'\')'


def _typed_expr(spec: ColumnSpec) -> str:
    return f"TRY_CAST({_raw_expr(spec.name)} AS {spec.sql_type})"


def _fingerprint_expr(columns: Iterable[ColumnSpec]) -> str:
    parts = [
        f'''CASE
            WHEN "{spec.name}" IS NULL THEN '-1:'
            ELSE LENGTH(CAST("{spec.name}" AS VARCHAR))::VARCHAR
                 || ':' || CAST("{spec.name}" AS VARCHAR)
        END'''
        for spec in columns
    ]
    return "SHA256(CONCAT(" + ", ".join(parts) + "))"


def _reject_reason_expr(spec: ColumnSpec) -> str:
    raw = _raw_expr(spec.name)
    typed = _typed_expr(spec)
    clauses: list[str] = []
    if not spec.nullable:
        clauses.append(f"WHEN {raw} IS NULL THEN '{spec.name}:missing' ")
    clauses.append(
        f"WHEN {raw} IS NOT NULL AND {typed} IS NULL THEN '{spec.name}:parse_error' "
    )
    if spec.domain_sql:
        domain = spec.domain_sql.format(value=typed)
        clauses.append(
            f"WHEN {raw} IS NOT NULL AND {typed} IS NOT NULL AND NOT ({domain}) "
            f"THEN '{spec.name}:domain_error' "
        )
    return "CASE " + "".join(clauses) + "ELSE NULL END"
