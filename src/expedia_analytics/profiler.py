from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths

TRAIN_REQUIRED_COLUMNS: tuple[str, ...] = (
    "date_time",
    "site_name",
    "posa_continent",
    "user_location_country",
    "user_location_region",
    "user_location_city",
    "orig_destination_distance_key",
    "orig_destination_distance",
    "user_id",
    "is_mobile",
    "is_package",
    "channel",
    "srch_ci",
    "srch_co",
    "srch_adults_cnt",
    "srch_children_cnt",
    "srch_rm_cnt",
    "srch_destination_id",
    "srch_destination_type_id",
    "is_booking",
    "cnt",
    "hotel_continent",
    "hotel_country",
    "hotel_market",
    "hotel_cluster",
)

CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "site_name",
    "posa_continent",
    "user_location_country",
    "is_mobile",
    "is_package",
    "channel",
    "srch_destination_type_id",
    "is_booking",
    "hotel_continent",
    "hotel_country",
    "hotel_market",
    "hotel_cluster",
)

NUMERIC_EXPRESSIONS: dict[str, str] = {
    "source_cnt": "cnt::DOUBLE",
    "orig_destination_distance": "orig_destination_distance::DOUBLE",
    "lead_time_days": "DATE_DIFF('day', CAST(date_time AS DATE), srch_ci)::DOUBLE",
    "stay_nights": "DATE_DIFF('day', srch_ci, srch_co)::DOUBLE",
    "adults": "srch_adults_cnt::DOUBLE",
    "children": "srch_children_cnt::DOUBLE",
    "rooms": "srch_rm_cnt::DOUBLE",
    "party_size": "(COALESCE(srch_adults_cnt, 0) + COALESCE(srch_children_cnt, 0))::DOUBLE",
}

QUANTILES: tuple[float, ...] = (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _connect(*, threads: int, memory_limit: str, temp_dir: Path) -> Any:
    import duckdb

    temp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads = {max(1, threads)}")
    con.execute(f"SET memory_limit = '{memory_limit.replace(chr(39), chr(39) * 2)}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = true")
    con.execute(f"SET temp_directory = '{_sql_path(temp_dir)}'")
    return con


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _schema(con: Any, relation: str) -> list[dict[str, Any]]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    return [
        {
            "column_name": row[0],
            "column_type": row[1],
            "null": row[2],
            "key": row[3],
            "default": row[4],
            "extra": row[5],
        }
        for row in rows
    ]


def _validate_schema(schema: list[dict[str, Any]]) -> None:
    actual = {item["column_name"] for item in schema}
    missing = sorted(set(TRAIN_REQUIRED_COLUMNS) - actual)
    if missing:
        raise RuntimeError("Prepared train schema is missing columns: " + ", ".join(missing))


def _null_profile(con: Any) -> list[dict[str, Any]]:
    expressions = []
    for column in TRAIN_REQUIRED_COLUMNS:
        expressions.append(
            f"COUNT(*) FILTER (WHERE {column} IS NULL)::BIGINT AS \"{column}\""
        )
    row = con.execute("SELECT " + ",\n".join(expressions) + " FROM raw_train").fetchone()
    total_rows = int(con.execute("SELECT COUNT(*) FROM raw_train").fetchone()[0])
    return [
        {
            "column": column,
            "null_rows": int(row[index]),
            "null_rate": float(row[index]) / total_rows if total_rows else None,
        }
        for index, column in enumerate(TRAIN_REQUIRED_COLUMNS)
    ]


def _numeric_profile(con: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    quantiles_sql = "[" + ", ".join(str(item) for item in QUANTILES) + "]"
    for name, expression in NUMERIC_EXPRESSIONS.items():
        row = con.execute(
            f"""
            WITH values_to_profile AS (
                SELECT {expression} AS value
                FROM raw_train
            )
            SELECT
                COUNT(value)::BIGINT,
                COUNT(*) FILTER (WHERE value IS NULL)::BIGINT,
                MIN(value),
                MAX(value),
                AVG(value),
                STDDEV_POP(value),
                APPROX_QUANTILE(value, {quantiles_sql})
            FROM values_to_profile
            """
        ).fetchone()
        result.append(
            {
                "metric": name,
                "valid_rows": int(row[0]),
                "null_rows": int(row[1]),
                "min": row[2],
                "max": row[3],
                "mean": row[4],
                "stddev": row[5],
                "quantile_probabilities": list(QUANTILES),
                "quantile_values": list(row[6]) if row[6] is not None else None,
            }
        )
    return result


def _categorical_profile(con: Any, *, top_n: int = 20) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for column in CATEGORICAL_COLUMNS:
        summary = con.execute(
            f"""
            SELECT
                COUNT(DISTINCT {column})::BIGINT,
                COUNT(*) FILTER (WHERE {column} IS NULL)::BIGINT
            FROM raw_train
            """
        ).fetchone()
        top_rows = con.execute(
            f"""
            SELECT CAST({column} AS VARCHAR) AS value, COUNT(*)::BIGINT AS rows
            FROM raw_train
            GROUP BY {column}
            ORDER BY rows DESC, value
            LIMIT {int(top_n)}
            """
        ).fetchall()
        result.append(
            {
                "column": column,
                "distinct_non_null": int(summary[0]),
                "null_rows": int(summary[1]),
                "top_values": [
                    {"value": value, "rows": int(rows)} for value, rows in top_rows
                ],
            }
        )
    return result


def _quality_profile(con: Any) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT
            COUNT(*)::BIGINT AS total_rows,
            COUNT(*) FILTER (WHERE user_id IS NULL)::BIGINT AS anonymous_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            COUNT(*) FILTER (WHERE is_booking = 0)::BIGINT AS non_booking_rows,
            COUNT(*) FILTER (WHERE is_booking NOT IN (0, 1) OR is_booking IS NULL)::BIGINT
                AS invalid_booking_rows,
            COUNT(*) FILTER (WHERE cnt IS NULL)::BIGINT AS null_cnt_rows,
            COUNT(*) FILTER (WHERE cnt <= 0)::BIGINT AS nonpositive_cnt_rows,
            COUNT(*) FILTER (WHERE srch_ci IS NULL)::BIGINT AS null_checkin_rows,
            COUNT(*) FILTER (WHERE srch_co IS NULL)::BIGINT AS null_checkout_rows,
            COUNT(*) FILTER (
                WHERE srch_ci IS NOT NULL
                  AND DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) < 0
            )::BIGINT AS negative_lead_time_rows,
            COUNT(*) FILTER (
                WHERE srch_ci IS NOT NULL
                  AND srch_co IS NOT NULL
                  AND DATE_DIFF('day', srch_ci, srch_co) <= 0
            )::BIGINT AS nonpositive_stay_rows,
            COUNT(*) FILTER (WHERE srch_adults_cnt IS NULL OR srch_adults_cnt <= 0)::BIGINT
                AS invalid_adults_rows,
            COUNT(*) FILTER (WHERE srch_children_cnt < 0)::BIGINT AS invalid_children_rows,
            COUNT(*) FILTER (WHERE srch_rm_cnt IS NULL OR srch_rm_cnt <= 0)::BIGINT
                AS invalid_rooms_rows,
            COUNT(*) FILTER (WHERE orig_destination_distance IS NULL)::BIGINT
                AS missing_distance_rows,
            COUNT(*) FILTER (WHERE srch_destination_id IS NULL)::BIGINT
                AS missing_destination_rows,
            COUNT(DISTINCT user_id)::BIGINT AS identified_users,
            COUNT(DISTINCT srch_destination_id)::BIGINT AS destinations,
            MIN(CAST(date_time AS DATE)) AS min_event_date,
            MAX(CAST(date_time AS DATE)) AS max_event_date,
            MIN(srch_ci) AS min_checkin_date,
            MAX(srch_ci) AS max_checkin_date,
            MIN(srch_co) AS min_checkout_date,
            MAX(srch_co) AS max_checkout_date,
            SUM(cnt) FILTER (WHERE cnt > 0)::HUGEINT AS valid_similar_event_count
        FROM raw_train
        """
    ).fetchone()
    columns = [item[0] for item in con.description]
    return dict(zip(columns, row, strict=True))


def _hash_duplicate_profile(con: Any) -> dict[str, Any]:
    columns = ", ".join(TRAIN_REQUIRED_COLUMNS)
    row = con.execute(
        f"""
        WITH grouped AS (
            SELECT HASH({columns}) AS row_hash, COUNT(*)::BIGINT AS rows_in_group
            FROM raw_train
            GROUP BY row_hash
        )
        SELECT
            COUNT(*) FILTER (WHERE rows_in_group > 1)::BIGINT AS duplicate_hash_groups,
            COALESCE(SUM(rows_in_group) FILTER (WHERE rows_in_group > 1), 0)::BIGINT
                AS rows_in_duplicate_hash_groups,
            COALESCE(SUM(rows_in_group - 1) FILTER (WHERE rows_in_group > 1), 0)::BIGINT
                AS excess_duplicate_rows,
            MAX(rows_in_group)::BIGINT AS largest_hash_group
        FROM grouped
        """
    ).fetchone()
    columns_out = [item[0] for item in con.description]
    return dict(zip(columns_out, row, strict=True))


def _proxy_context_profile(con: Any) -> dict[str, Any]:
    row = con.execute(
        """
        WITH contexts AS (
            SELECT
                user_id,
                date_time,
                site_name,
                posa_continent,
                user_location_country,
                user_location_region,
                user_location_city,
                is_mobile,
                is_package,
                channel,
                srch_ci,
                srch_co,
                srch_adults_cnt,
                srch_children_cnt,
                srch_rm_cnt,
                srch_destination_id,
                srch_destination_type_id,
                COUNT(*)::BIGINT AS interaction_rows,
                COUNT(DISTINCT hotel_cluster)::BIGINT AS distinct_hotel_clusters,
                COUNT(DISTINCT hotel_market)::BIGINT AS distinct_hotel_markets,
                COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows
            FROM raw_train
            WHERE user_id IS NOT NULL
            GROUP BY ALL
        )
        SELECT
            COUNT(*)::BIGINT AS proxy_contexts,
            SUM(interaction_rows)::BIGINT AS eligible_interaction_rows,
            COUNT(*) FILTER (WHERE interaction_rows > 1)::BIGINT AS multirow_contexts,
            COUNT(*) FILTER (WHERE distinct_hotel_clusters > 1)::BIGINT
                AS multicluster_contexts,
            COUNT(*) FILTER (WHERE distinct_hotel_markets > 1)::BIGINT
                AS multimarket_contexts,
            COUNT(*) FILTER (WHERE booking_rows > 0)::BIGINT AS booking_bearing_contexts,
            COUNT(*) FILTER (WHERE booking_rows > 1)::BIGINT AS multibooking_contexts,
            AVG(interaction_rows) AS avg_rows_per_context,
            APPROX_QUANTILE(interaction_rows, [0.5, 0.9, 0.99, 1.0]) AS rows_quantiles,
            APPROX_QUANTILE(distinct_hotel_clusters, [0.5, 0.9, 0.99, 1.0])
                AS cluster_quantiles
        FROM contexts
        """
    ).fetchone()
    columns = [item[0] for item in con.description]
    return dict(zip(columns, row, strict=True))


def _destination_profile(con: Any) -> dict[str, Any]:
    summary = con.execute(
        """
        SELECT
            COUNT(*)::BIGINT AS rows,
            COUNT(DISTINCT srch_destination_id)::BIGINT AS distinct_destination_ids,
            COUNT(*) - COUNT(DISTINCT srch_destination_id) AS duplicate_destination_rows,
            COUNT(*) FILTER (WHERE srch_destination_id IS NULL)::BIGINT
                AS null_destination_ids
        FROM raw_destinations
        """
    ).fetchone()
    columns = [item[0] for item in con.description]
    result = dict(zip(columns, summary, strict=True))

    feature_queries = []
    for index in range(1, 150):
        feature = f"d{index}"
        feature_queries.append(
            f"""
            SELECT '{feature}' AS feature,
                   COUNT(*) FILTER (WHERE {feature} IS NULL)::BIGINT AS null_rows,
                   MIN({feature}) AS min_value,
                   MAX({feature}) AS max_value,
                   AVG({feature}) AS mean_value
            FROM raw_destinations
            """
        )
    rows = con.execute(" UNION ALL ".join(feature_queries)).fetchall()
    total_rows = int(result["rows"])
    result["latent_features"] = [
        {
            "feature": feature,
            "null_rows": int(null_rows),
            "null_rate": float(null_rows) / total_rows if total_rows else None,
            "min": min_value,
            "max": max_value,
            "mean": mean_value,
        }
        for feature, null_rows, min_value, max_value, mean_value in rows
    ]
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, int) and abs(value) > 2**63 - 1:
        return str(value)
    return value


def _render_markdown(profile: dict[str, Any]) -> str:
    quality = profile["train"]["quality"]
    lines = [
        "# Expedia source profiling report",
        "",
        f"Build time (UTC): `{profile['generated_utc']}`",
        "",
        "## Source coverage",
        "",
        f"- rows: **{quality['total_rows']:,}**",
        f"- event period: **{quality['min_event_date']} — {quality['max_event_date']}**",
        f"- identified users: **{quality['identified_users']:,}**",
        f"- destinations: **{quality['destinations']:,}**",
        f"- booking rows: **{quality['booking_rows']:,}**",
        f"- non-booking rows: **{quality['non_booking_rows']:,}**",
        f"- anonymous rows: **{quality['anonymous_rows']:,}**",
        "",
        "## Critical semantic warnings",
        "",
        "1. The source has no explicit session or search-request identifier.",
        "2. `cnt` is profiled separately and is not silently converted into booking count.",
        "3. Product rates from this competition dataset are descriptive of the supplied sample,",
        "   not audited Expedia-wide business KPIs.",
        "4. `d1`–`d149` are latent destination features and are not business-interpretable.",
        "",
        "## Data-quality counts",
        "",
    ]
    for key in (
        "invalid_booking_rows",
        "null_cnt_rows",
        "nonpositive_cnt_rows",
        "null_checkin_rows",
        "null_checkout_rows",
        "negative_lead_time_rows",
        "nonpositive_stay_rows",
        "invalid_adults_rows",
        "invalid_children_rows",
        "invalid_rooms_rows",
        "missing_distance_rows",
        "missing_destination_rows",
    ):
        lines.append(f"- `{key}`: {quality[key]:,}")

    if profile["train"].get("proxy_contexts"):
        context = profile["train"]["proxy_contexts"]
        lines.extend(
            [
                "",
                "## Strict proxy-context diagnostics",
                "",
                f"- proxy contexts: **{context['proxy_contexts']:,}**",
                f"- multi-row contexts: **{context['multirow_contexts']:,}**",
                f"- multi-cluster contexts: **{context['multicluster_contexts']:,}**",
                f"- multi-market contexts: **{context['multimarket_contexts']:,}**",
                f"- booking-bearing contexts: **{context['booking_bearing_contexts']:,}**",
                "",
            ]
        )

    lines.extend(
        [
            "## Next design decision",
            "",
            "Segment boundaries, blocking DQ thresholds and dashboard denominators must be",
            "confirmed from this profile before the final marts are frozen.",
            "",
        ]
    )
    return "\n".join(lines)


def profile_sources(
    paths: AnalyticsPaths,
    *,
    threads: int = 7,
    memory_limit: str = "32GB",
    deep: bool = False,
) -> dict[str, Any]:
    """Profile prepared Expedia sources before freezing analytical semantics."""
    for path in (paths.train_path, paths.destinations_path):
        if not path.exists():
            raise FileNotFoundError(f"Prepared source is missing: {path}")

    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    generated_utc = datetime.now(UTC)
    temp_dir = paths.analytics_dir / "profile_tmp"
    con = _connect(threads=threads, memory_limit=memory_limit, temp_dir=temp_dir)
    try:
        con.execute(
            f"CREATE VIEW raw_train AS SELECT * FROM read_parquet('{_sql_path(paths.train_path)}')"
        )
        con.execute(
            "CREATE VIEW raw_destinations AS "
            f"SELECT * FROM read_parquet('{_sql_path(paths.destinations_path)}')"
        )
        train_schema = _schema(con, "raw_train")
        _validate_schema(train_schema)
        profile: dict[str, Any] = {
            "generated_utc": generated_utc.isoformat(),
            "elapsed_seconds": None,
            "configuration": {
                "threads": threads,
                "memory_limit": memory_limit,
                "deep": deep,
            },
            "runtime": {
                "python": sys.version,
                "platform": platform.platform(),
            },
            "sources": {
                "train": {
                    "path": str(paths.train_path),
                    "bytes": paths.train_path.stat().st_size,
                    "modified_utc": datetime.fromtimestamp(
                        paths.train_path.stat().st_mtime, tz=UTC
                    ).isoformat(),
                    "sha256": _file_sha256(paths.train_path),
                },
                "destinations": {
                    "path": str(paths.destinations_path),
                    "bytes": paths.destinations_path.stat().st_size,
                    "modified_utc": datetime.fromtimestamp(
                        paths.destinations_path.stat().st_mtime, tz=UTC
                    ).isoformat(),
                    "sha256": _file_sha256(paths.destinations_path),
                },
            },
            "train": {
                "schema": train_schema,
                "quality": _quality_profile(con),
                "nulls": _null_profile(con),
                "numeric": _numeric_profile(con),
                "categorical": _categorical_profile(con),
            },
            "destinations": {
                "schema": _schema(con, "raw_destinations"),
                **_destination_profile(con),
            },
            "limitations": [
                "No explicit session_id or search_request_id is present.",
                "cnt is a similar-event count and is not an observed booking count.",
                "The competition sample is not guaranteed to represent Expedia-wide traffic.",
                "Event timestamp timezone is not specified by the supplied schema.",
                "Destination latent features d1-d149 have no business interpretation.",
            ],
        }
        if deep:
            profile["train"]["hash_duplicate_diagnostics"] = _hash_duplicate_profile(con)
            profile["train"]["proxy_contexts"] = _proxy_context_profile(con)
    finally:
        con.close()

    profile["elapsed_seconds"] = time.monotonic() - started
    safe_profile = _json_safe(profile)
    json_path = paths.artifacts_dir / "source_profile.json"
    markdown_path = paths.artifacts_dir / "source_profile.md"
    json_path.write_text(
        json.dumps(safe_profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(_render_markdown(safe_profile), encoding="utf-8")
    print(f"[analytics] source profile: {json_path}")
    print(f"[analytics] source profile summary: {markdown_path}")
    return safe_profile
