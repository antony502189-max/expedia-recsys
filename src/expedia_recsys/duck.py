from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def sql_path(path: Path) -> str:
    """Return a path escaped for use as a DuckDB SQL string literal."""
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def connect(database_path: Path, threads: int, memory_limit: str) -> duckdb.DuckDBPyConnection:
    import duckdb

    database_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database_path))
    con.execute(f"SET threads = {max(1, threads)}")
    con.execute(f"SET memory_limit = '{memory_limit.replace(chr(39), chr(39) * 2)}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = true")
    return con
