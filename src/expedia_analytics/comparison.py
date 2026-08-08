from __future__ import annotations

import json
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import PUBLISHED_OBJECTS
from expedia_analytics.final_common import _sql_path


def _load_manifest(paths: AnalyticsPaths, build_id: str) -> dict[str, Any]:
    path = paths.artifacts_dir / build_id / "build_manifest.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def compare_builds(
    paths: AnalyticsPaths,
    left_build: str,
    right_build: str,
    *,
    exact: bool = False,
) -> dict[str, Any]:
    """Compare two immutable builds without materializing full-table differences in Python.

    Logical checksums are compared first. In exact mode schemas and row counts are checked before
    running a one-direction ``EXCEPT ALL`` existence test. With equal cardinality, proving that the
    left multiset is contained in the right multiset is sufficient to prove exact multiset equality.
    """

    left = _load_manifest(paths, left_build)
    right = _load_manifest(paths, right_build)

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
            con.execute("SET preserve_insertion_order=false")
            con.execute(f"ATTACH '{_sql_path(left_database)}' AS left_build (READ_ONLY)")
            con.execute(f"ATTACH '{_sql_path(right_database)}' AS right_build (READ_ONLY)")

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

                left_manifest_object = left_objects.get(spec.name)
                right_manifest_object = right_objects.get(spec.name)
                left_rows = (
                    int(left_manifest_object["logical_checksum"]["rows"])
                    if left_manifest_object is not None
                    else None
                )
                right_rows = (
                    int(right_manifest_object["logical_checksum"]["rows"])
                    if right_manifest_object is not None
                    else None
                )
                row_counts_match = left_rows is not None and left_rows == right_rows

                left_minus_right_empty: bool | None = None
                if schemas_match and row_counts_match:
                    left_minus_right_empty = bool(
                        con.execute(
                            f"""
                            SELECT NOT EXISTS (
                                SELECT 1
                                FROM (
                                    SELECT * FROM {left_relation}
                                    EXCEPT ALL
                                    SELECT * FROM {right_relation}
                                ) AS exact_difference
                                LIMIT 1
                            )
                            """
                        ).fetchone()[0]
                    )

                same = bool(
                    schemas_match
                    and row_counts_match
                    and left_minus_right_empty is True
                )
                exact_identical = exact_identical and same
                exact_rows.append(
                    {
                        "object": spec.name,
                        "schemas_match": schemas_match,
                        "left_rows": left_rows,
                        "right_rows": right_rows,
                        "row_counts_match": row_counts_match,
                        "left_minus_right_empty": left_minus_right_empty,
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
        "exact_method": (
            "schema + equal row counts + one-direction EXCEPT ALL emptiness"
            if exact
            else None
        ),
        "exact_objects": exact_rows,
    }
