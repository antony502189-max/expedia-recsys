from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import (
    PROHIBITED_PUBLIC_TERMS,
    PUBLISHED_OBJECTS,
    ObjectSpec,
)
from expedia_analytics.final_common import _sha256_file, _sql_path


def _query_scalar(con: Any, query: str) -> Any:
    row = con.execute(query).fetchone()
    return None if row is None else row[0]


def _schema_for(spec: ObjectSpec) -> str:
    return "staging" if spec.layer == "staging" else "analytics"


def _table_columns(con: Any, table: str, *, schema: str = "analytics") -> list[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {schema}.{table}").fetchall()
    return [str(row[0]) for row in rows]


def _logical_checksum(con: Any, spec: ObjectSpec) -> dict[str, Any]:
    schema = _schema_for(spec)
    columns = _table_columns(con, spec.name, schema=schema)
    identifiers = ", ".join(f'"{column}"' for column in columns)
    row = con.execute(
        f"""
        WITH row_hashes AS (
            SELECT HASH({identifiers})::UBIGINT AS row_hash
            FROM {schema}.{spec.name}
        )
        SELECT
            COUNT(*)::BIGINT,
            COALESCE(SUM(row_hash)::HUGEINT, 0),
            COALESCE(BIT_XOR(row_hash), 0),
            COALESCE(MIN(row_hash), 0),
            COALESCE(MAX(row_hash), 0)
        FROM row_hashes
        """
    ).fetchone()
    return {
        "algorithm": "duckdb-hash-multiset-v2",
        "rows": int(row[0]),
        "hash_sum": str(row[1]),
        "hash_xor": str(row[2]),
        "hash_min": str(row[3]),
        "hash_max": str(row[4]),
        "columns": columns,
    }


def _validate_unique_grain(con: Any, spec: ObjectSpec) -> dict[str, Any]:
    schema = _schema_for(spec)
    keys = ", ".join(f'"{key}"' for key in spec.grain)
    duplicates = int(
        _query_scalar(
            con,
            f"""
            SELECT COUNT(*) FROM (
                SELECT {keys}, COUNT(*) AS n
                FROM {schema}.{spec.name}
                GROUP BY {keys}
                HAVING COUNT(*) > 1
            )
            """,
        )
    )
    return {
        "name": f"{spec.name}:grain_unique",
        "passed": duplicates == 0,
        "actual": duplicates,
        "expected": 0,
    }


def _quality_gates(con: Any, contract: dict[str, Any]) -> dict[str, Any]:
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

    def equal(name: str, actual_query: str, expected_query: str) -> None:
        actual = _query_scalar(con, actual_query)
        expected = _query_scalar(con, expected_query)
        add(name, actual, expected, actual == expected)

    for source in ("train", "test", "destinations"):
        accepted = (
            f"stg_{source}_accepted" if source != "destinations" else "stg_destinations_accepted"
        )
        quarantine = f"quarantine_{source}"
        equal(
            f"{source}_raw_equals_accepted_plus_quarantine",
            f"SELECT COUNT(*) FROM raw.{source}_landing",
            f"SELECT (SELECT COUNT(*) FROM staging.{accepted}) + "
            f"(SELECT COUNT(*) FROM staging.{quarantine})",
        )
        reconciliation = (
            f"meta_{source}_multiset_reconciliation"
            if source != "destinations"
            else "meta_destinations_multiset_reconciliation"
        )
        equal(
            f"{source}_content_multiset_reconciles",
            f"SELECT COUNT(*) FROM staging.{reconciliation} WHERE NOT reconciles",
            "SELECT 0",
        )

    equal(
        "fact_equals_accepted_train",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions",
        "SELECT COUNT(*) FROM staging.stg_train_accepted",
    )
    equal(
        "proxy_fact_covers_identified_interactions",
        "SELECT SUM(interaction_rows) FROM analytics.fct_proxy_search_contexts",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE user_id IS NOT NULL",
    )
    equal(
        "user_day_proxy_contexts_reconcile",
        "SELECT SUM(proxy_contexts) FROM analytics.fct_user_day",
        "SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts",
    )
    equal(
        "daily_interactions_reconcile",
        "SELECT SUM(interaction_rows) FROM analytics.dm_interaction_outcome_daily",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions",
    )
    equal(
        "monthly_interactions_reconcile",
        "SELECT SUM(interaction_rows) FROM analytics.dm_interaction_outcome_monthly",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions",
    )
    equal(
        "daily_booking_rows_reconcile",
        "SELECT SUM(booking_rows) FROM analytics.dm_interaction_outcome_daily",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE is_booking = 1",
    )
    equal(
        "monthly_booking_rows_reconcile",
        "SELECT SUM(booking_rows) FROM analytics.dm_interaction_outcome_monthly",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE is_booking = 1",
    )
    equal(
        "proxy_daily_reconcile",
        "SELECT SUM(proxy_search_contexts) FROM analytics.dm_proxy_context_daily",
        "SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts",
    )
    equal(
        "proxy_monthly_reconcile",
        "SELECT SUM(proxy_search_contexts) FROM analytics.dm_proxy_context_monthly",
        "SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts",
    )
    equal(
        "destination_monthly_population_reconciles",
        "SELECT SUM(interaction_rows) FROM analytics.dm_destination_monthly",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
        "WHERE srch_destination_id IS NOT NULL",
    )
    equal(
        "destination_performance_population_reconciles",
        "SELECT SUM(interaction_rows) FROM analytics.dm_destination_performance",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
        "WHERE srch_destination_id IS NOT NULL",
    )
    equal(
        "hotel_market_population_reconciles",
        "SELECT SUM(interaction_rows) FROM analytics.dm_hotel_market_performance",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions WHERE hotel_market IS NOT NULL",
    )
    equal(
        "route_population_reconciles",
        "SELECT SUM(interaction_rows) FROM analytics.dm_origin_destination_routes",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
        "WHERE srch_destination_id IS NOT NULL",
    )
    equal(
        "bridge_population_reconciles",
        "SELECT SUM(interaction_rows) FROM analytics.bridge_destination_hotel_market",
        "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
        "WHERE srch_destination_id IS NOT NULL AND hotel_market IS NOT NULL",
    )

    rate_failures = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM (
                SELECT booking_interaction_share AS rate
                FROM analytics.dm_interaction_outcome_daily
                UNION ALL SELECT weighted_booking_event_share
                FROM analytics.dm_interaction_outcome_daily
                UNION ALL SELECT booking_interaction_share
                FROM analytics.dm_interaction_outcome_monthly
                UNION ALL SELECT weighted_booking_event_share
                FROM analytics.dm_interaction_outcome_monthly
                UNION ALL SELECT booking_bearing_proxy_context_share
                FROM analytics.dm_proxy_context_daily
                UNION ALL SELECT proxy_interaction_coverage
                FROM analytics.dm_proxy_context_daily
                UNION ALL SELECT booking_bearing_proxy_context_share
                FROM analytics.dm_proxy_context_monthly
                UNION ALL SELECT proxy_interaction_coverage
                FROM analytics.dm_proxy_context_monthly
                UNION ALL SELECT booking_user_day_share
                FROM analytics.dm_user_day_daily
                UNION ALL SELECT booking_user_share
                FROM analytics.dm_user_day_monthly
                UNION ALL SELECT booking_interaction_share
                FROM analytics.dm_segment_daily
                UNION ALL SELECT booking_interaction_share
                FROM analytics.dm_segment_monthly
                UNION ALL SELECT booking_interaction_share
                FROM analytics.dm_destination_performance
                UNION ALL SELECT booking_interaction_share
                FROM analytics.dm_hotel_market_performance
                UNION ALL SELECT missing_share
                FROM analytics.dm_missingness_daily
                UNION ALL SELECT affected_share
                FROM analytics.dm_proxy_context_ambiguity
                UNION ALL SELECT share_within_booking_population
                FROM analytics.dm_booking_population_drift
                UNION ALL SELECT observed_recurrence_share
                FROM analytics.dm_observed_recurrence
                WHERE NOT is_right_censored
            ) rates
            WHERE rate IS NOT NULL AND (rate < 0 OR rate > 1)
            """,
        )
    )
    add("all_published_rates_bounded", rate_failures, 0, rate_failures == 0)

    numerator_failures = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM (
                SELECT booking_rows, interaction_rows
                FROM analytics.dm_interaction_outcome_daily
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_interaction_outcome_monthly
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_segment_daily
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_segment_monthly
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_destination_performance
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_hotel_market_performance
                UNION ALL SELECT booking_rows, interaction_rows
                FROM analytics.dm_origin_destination_routes
            ) values_to_check
            WHERE booking_rows < 0 OR interaction_rows < 0 OR booking_rows > interaction_rows
            """,
        )
    )
    add(
        "numerators_do_not_exceed_denominators",
        numerator_failures,
        0,
        numerator_failures == 0,
    )

    interval_failures = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM (
                SELECT booking_interaction_share AS rate,
                       booking_interaction_share_ci_low AS low,
                       booking_interaction_share_ci_high AS high
                FROM analytics.dm_destination_performance
                UNION ALL
                SELECT booking_interaction_share,
                       booking_interaction_share_ci_low,
                       booking_interaction_share_ci_high
                FROM analytics.dm_hotel_market_performance
                UNION ALL
                SELECT booking_interaction_share,
                       booking_interaction_share_ci_low,
                       booking_interaction_share_ci_high
                FROM analytics.dm_booking_window
            ) intervals
            WHERE low < 0 OR high > 1 OR low > rate OR high < rate OR low > high
            """,
        )
    )
    add("wilson_intervals_are_valid", interval_failures, 0, interval_failures == 0)

    date_gaps = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM (
                SELECT date_day, LAG(date_day) OVER (ORDER BY date_day) AS previous_date
                FROM analytics.dim_date
            ) dates
            WHERE previous_date IS NOT NULL
              AND DATE_DIFF('day', previous_date, date_day) <> 1
            """,
        )
    )
    add("date_spine_is_continuous", date_gaps, 0, date_gaps == 0)

    daily_monthly_failures = int(
        _query_scalar(
            con,
            """
            WITH daily AS (
                SELECT DATE_TRUNC('month', event_date)::DATE AS event_month,
                       SUM(interaction_rows)::BIGINT AS interaction_rows,
                       SUM(booking_rows)::BIGINT AS booking_rows
                FROM analytics.dm_interaction_outcome_daily
                GROUP BY event_month
            )
            SELECT COUNT(*)
            FROM daily d
            FULL OUTER JOIN analytics.dm_interaction_outcome_monthly m USING (event_month)
            WHERE COALESCE(d.interaction_rows, -1) <> COALESCE(m.interaction_rows, -1)
               OR COALESCE(d.booking_rows, -1) <> COALESCE(m.booking_rows, -1)
            """,
        )
    )
    add(
        "daily_to_monthly_outcomes_reconcile",
        daily_monthly_failures,
        0,
        daily_monthly_failures == 0,
    )

    segment_daily_failures = int(
        _query_scalar(
            con,
            """
            WITH expected AS (
                SELECT
                    event_date,
                    segment_type,
                    (SELECT COUNT(*) FROM analytics.fct_hotel_interactions i
                     WHERE i.event_date = d.event_date) AS expected_rows,
                    SUM(interaction_rows) AS actual_rows
                FROM analytics.dm_segment_daily d
                GROUP BY event_date, segment_type
            )
            SELECT COUNT(*) FROM expected WHERE expected_rows <> actual_rows
            """,
        )
    )
    add(
        "each_daily_segment_type_reconciles",
        segment_daily_failures,
        0,
        segment_daily_failures == 0,
    )

    segment_monthly_failures = int(
        _query_scalar(
            con,
            """
            WITH expected AS (
                SELECT
                    event_month,
                    segment_type,
                    (SELECT COUNT(*) FROM analytics.fct_hotel_interactions i
                     WHERE i.event_month = d.event_month) AS expected_rows,
                    SUM(interaction_rows) AS actual_rows
                FROM analytics.dm_segment_monthly d
                GROUP BY event_month, segment_type
            )
            SELECT COUNT(*) FROM expected WHERE expected_rows <> actual_rows
            """,
        )
    )
    add(
        "each_monthly_segment_type_reconciles",
        segment_monthly_failures,
        0,
        segment_monthly_failures == 0,
    )

    age_zero_failures = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM analytics.dm_observed_recurrence
            WHERE observed_age_month = 0
              AND (is_right_censored OR ABS(observed_recurrence_share - 1.0) > 1e-12)
            """,
        )
    )
    add(
        "observed_recurrence_age_zero_is_one",
        age_zero_failures,
        0,
        age_zero_failures == 0,
    )
    censored_value_failures = int(
        _query_scalar(
            con,
            """
            SELECT COUNT(*) FROM analytics.dm_observed_recurrence
            WHERE is_right_censored
              AND (observed_active_users IS NOT NULL
                   OR observed_recurrence_share IS NOT NULL
                   OR observed_booking_users IS NOT NULL)
            """,
        )
    )
    add(
        "right_censored_recurrence_cells_are_null",
        censored_value_failures,
        0,
        censored_value_failures == 0,
    )

    for spec in PUBLISHED_OBJECTS:
        schema = _schema_for(spec)
        exists = int(
            _query_scalar(
                con,
                "SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema = '{schema}' AND table_name = '{spec.name}'",
            )
        )
        add(f"{spec.name}:exists", exists, 1, exists == 1)
        if not exists:
            continue
        checks.append(_validate_unique_grain(con, spec))
        rows = int(_query_scalar(con, f"SELECT COUNT(*) FROM {schema}.{spec.name}"))
        if not spec.name.startswith("quarantine_"):
            add(f"{spec.name}:non_empty", rows, ">0", rows > 0)

    public_names = [spec.name for spec in PUBLISHED_OBJECTS if spec.layer == "mart"]
    public_columns: list[str] = []
    for name in public_names:
        public_columns.extend(_table_columns(con, name))
    prohibited_hits = sorted(
        {
            term
            for term in PROHIBITED_PUBLIC_TERMS
            if any(term in value.lower() for value in [*public_names, *public_columns])
        }
    )
    add("no_prohibited_public_metric_terms", prohibited_hits, [], not prohibited_hits)

    max_quarantine = float(contract["quality_thresholds"]["maximum_quarantine_rate"])
    for source in ("train", "test", "destinations"):
        rate = float(
            _query_scalar(
                con,
                f"SELECT safe_rate((SELECT COUNT(*) FROM staging.quarantine_{source}), "
                f"(SELECT COUNT(*) FROM raw.{source}_landing))",
            )
            or 0.0
        )
        add(
            f"{source}_quarantine_rate_within_contract",
            rate,
            f"<={max_quarantine}",
            rate <= max_quarantine,
        )

    multimarket_rate = float(
        _query_scalar(
            con,
            "SELECT affected_share FROM analytics.dm_proxy_context_ambiguity "
            "WHERE ambiguity_type = 'multimarket_context'",
        )
        or 0.0
    )
    max_multimarket = float(
        contract["quality_thresholds"]["maximum_proxy_multimarket_rate"]
    )
    add(
        "proxy_multimarket_rate_within_contract",
        multimarket_rate,
        f"<={max_multimarket}",
        multimarket_rate <= max_multimarket,
    )

    failures = [check for check in checks if not check["passed"]]
    return {
        "passed": not failures,
        "checks": checks,
        "failure_count": len(failures),
    }


def _copy_table(
    con: Any,
    *,
    spec: ObjectSpec,
    target_root: Path,
) -> dict[str, Any]:
    schema = _schema_for(spec)
    target = target_root / spec.name
    if spec.partition_by:
        target.mkdir(parents=True, exist_ok=True)
        partition = ", ".join(f'"{column}"' for column in spec.partition_by)
        con.execute(
            f"""
            COPY (SELECT * FROM {schema}.{spec.name})
            TO '{_sql_path(target)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY ({partition}))
            """
        )
        files = sorted(target.rglob("*.parquet"))
    else:
        target = target.with_suffix(".parquet")
        con.execute(
            f"""
            COPY {schema}.{spec.name}
            TO '{_sql_path(target)}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        files = [target]
    file_manifest = [
        {
            "path": str(path),
            "relative_path": str(path.relative_to(target_root)),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    return {
        "path": str(target),
        "files": len(files),
        "bytes": sum(item["bytes"] for item in file_manifest),
        "file_manifest": file_manifest,
    }


def _publish_pointer(paths: AnalyticsPaths, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary = paths.latest_pointer_path.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, paths.latest_pointer_path)
    marts_pointer = paths.marts_dir / "LATEST_BUILD.json"
    temp_marts = marts_pointer.with_suffix(".json.tmp")
    temp_marts.write_text(text, encoding="utf-8")
    os.replace(temp_marts, marts_pointer)
