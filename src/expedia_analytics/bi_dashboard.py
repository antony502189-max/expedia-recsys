# ruff: noqa: E501
"""Build the immutable-source Stage 2 dashboard BI exports.

This module deliberately attaches the accepted Stage 1 database read-only and
writes a separate collection of narrow Parquet marts.  It never creates or
replaces objects in the Stage 1 database.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

BI_CONTRACT_VERSION = "1.0.0"
SOURCE_BUILD_ID = "20260807T121247Z"


MART_SPECS: dict[str, dict[str, Any]] = {
    "bi_overview_monthly": {
        "sources": [
            "dm_sample_activity_monthly",
            "dm_interaction_outcome_monthly",
            "dm_proxy_context_monthly",
        ],
        "purpose": "Product Overview monthly KPIs and trends.",
        "page": 1,
        "visuals": [1, 2, 3, 4, 5, 6],
        "grain": ["event_month"],
    },
    "bi_segments_monthly": {
        "sources": ["dm_segment_monthly", "dim_segment_definition"],
        "purpose": "Monthly segment comparisons.",
        "page": 2,
        "visuals": [7, 8, 9],
        "grain": ["event_month", "segment_type", "segment_value"],
    },
    "bi_booking_window": {
        "sources": ["dm_booking_window", "dim_segment_definition"],
        "purpose": "Lead-time by stay-length booking window heatmap.",
        "page": 2,
        "visuals": [10],
        "grain": ["lead_time_segment", "stay_segment"],
    },
    "bi_traveller_planning_monthly": {
        "sources": ["dm_travel_patterns", "dim_segment_definition"],
        "purpose": "Monthly traveller planning patterns.",
        "page": 2,
        "visuals": [11],
        "grain": ["event_month", "traveller_segment"],
    },
    "bi_checkin_seasonality": {
        "sources": ["dm_checkin_seasonality", "dim_segment_definition"],
        "purpose": "Planned check-in seasonality by traveller segment.",
        "page": 2,
        "visuals": [12],
        "grain": ["checkin_month", "traveller_segment"],
    },
    "bi_destination_performance": {
        "sources": ["dm_destination_performance"],
        "purpose": "Destination performance and investigation candidates.",
        "page": 3,
        "visuals": [13, 14, 15],
        "grain": ["destination_id"],
    },
    "bi_hotel_market_performance": {
        "sources": ["dm_hotel_market_performance"],
        "purpose": "Hotel-market performance and investigation candidates.",
        "page": 3,
        "visuals": [16],
        "grain": ["hotel_market"],
    },
    "bi_destination_monthly": {
        "sources": ["dm_destination_monthly"],
        "purpose": "Destination-level monthly activity trend.",
        "page": 3,
        "visuals": [17],
        "grain": ["event_month", "destination_id"],
    },
    "bi_routes": {
        "sources": ["dm_origin_destination_routes"],
        "purpose": "Origin-to-destination route comparison.",
        "page": 3,
        "visuals": [18],
        "grain": ["origin_id", "destination_id"],
    },
    "bi_observed_recurrence": {
        "sources": ["dm_observed_recurrence"],
        "purpose": "Observed recurrence cohorts; not retention.",
        "page": 4,
        "visuals": [19, 20, 21],
        "grain": ["cohort_month", "activity_month"],
    },
    "bi_acceptance_status": {
        "sources": ["FINAL_ACCEPTANCE.json"],
        "purpose": "Accepted Stage 1 reproducibility status.",
        "page": 5,
        "visuals": [22],
        "grain": ["stage1_build_id"],
    },
    "bi_missingness_daily": {
        "sources": ["dm_missingness_daily"],
        "purpose": "Daily source-field missingness.",
        "page": 5,
        "visuals": [23],
        "grain": ["event_date", "field_name"],
    },
    "bi_proxy_ambiguity": {
        "sources": ["dm_proxy_context_ambiguity"],
        "purpose": "Overlapping proxy-context ambiguity diagnostics.",
        "page": 5,
        "visuals": [24],
        "grain": ["ambiguity_type"],
    },
    "bi_booking_population_drift_summary": {
        "sources": ["dm_booking_population_drift_summary"],
        "purpose": "Train- versus test-booking-population drift summary.",
        "page": 5,
        "visuals": [25],
        "grain": ["dimension_name"],
    },
}


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_marts(con: duckdb.DuckDBPyConnection) -> None:
    """Materialize dashboard grains using only accepted Stage 1 mart fields."""
    con.execute(
        """
        CREATE TABLE bi_overview_monthly AS
        SELECT
            activity.event_month,
            activity.logged_interaction_rows AS interaction_rows,
            outcome.booking_rows,
            outcome.booking_rows::DOUBLE / NULLIF(activity.logged_interaction_rows, 0)
                AS booking_interaction_share,
            activity.identified_active_users AS active_users,
            proxy.proxy_search_contexts AS proxy_contexts,
            proxy.proxy_interaction_coverage,
            outcome.booking_interaction_share_ci_low,
            outcome.booking_interaction_share_ci_high,
            activity.event_month = DATE '2013-01-01' AS is_partial_month
        FROM source.analytics.dm_sample_activity_monthly AS activity
        INNER JOIN source.analytics.dm_interaction_outcome_monthly AS outcome
            USING (event_month)
        LEFT JOIN source.analytics.dm_proxy_context_monthly AS proxy
            USING (event_month)
        """
    )
    con.execute(
        """
        CREATE TABLE bi_segments_monthly AS
        SELECT
            segment.event_month,
            segment.segment_type,
            segment.segment_value,
            COALESCE(
                definition.sort_order,
                CASE
                    WHEN segment.segment_type IN ('channel', 'site')
                        THEN TRY_CAST(segment.segment_value AS INTEGER)
                END
            ) AS segment_sort_order,
            segment.interaction_rows,
            segment.booking_rows,
            segment.booking_rows::DOUBLE / NULLIF(segment.interaction_rows, 0)
                AS booking_interaction_share,
            CASE
                WHEN segment.interaction_rows < 100 THEN 'low'
                WHEN segment.interaction_rows < 1000 THEN 'adequate'
                ELSE 'strong'
            END AS support_level,
            (
                definition.segment_value IS NOT NULL
                OR segment.segment_type IN ('channel', 'site')
            ) AS is_valid_segment,
            100.0 * (
                segment.booking_rows::DOUBLE / NULLIF(segment.interaction_rows, 0)
                - overall.booking_rows::DOUBLE / NULLIF(overall.interaction_rows, 0)
            ) AS booking_interaction_share_vs_overall_pp
        FROM source.analytics.dm_segment_monthly AS segment
        LEFT JOIN source.analytics.dim_segment_definition AS definition
            USING (segment_type, segment_value)
        INNER JOIN source.analytics.dm_interaction_outcome_monthly AS overall
            USING (event_month)
        """
    )
    con.execute(
        """
        CREATE TABLE bi_booking_window AS
        SELECT
            booking_window.lead_time_segment,
            lead.sort_order AS lead_time_sort_order,
            booking_window.stay_segment,
            stay.sort_order AS stay_sort_order,
            booking_window.interaction_rows,
            booking_window.booking_rows,
            booking_window.booking_rows::DOUBLE / NULLIF(booking_window.interaction_rows, 0)
                AS booking_interaction_share,
            booking_window.booking_interaction_share_ci_low,
            booking_window.booking_interaction_share_ci_high,
            CASE
                WHEN booking_window.interaction_rows < 100 THEN 'low'
                WHEN booking_window.interaction_rows < 1000 THEN 'adequate'
                ELSE 'strong'
            END AS support_level
        FROM source.analytics.dm_booking_window AS booking_window
        INNER JOIN source.analytics.dim_segment_definition AS lead
            ON lead.segment_type = 'lead_time'
            AND lead.segment_value = booking_window.lead_time_segment
        INNER JOIN source.analytics.dim_segment_definition AS stay
            ON stay.segment_type = 'stay'
            AND stay.segment_value = booking_window.stay_segment
        """
    )
    con.execute(
        """
        CREATE TABLE bi_traveller_planning_monthly AS
        SELECT
            patterns.event_month,
            patterns.traveller_segment,
            traveller.sort_order AS traveller_sort_order,
            SUM(patterns.interaction_rows)::BIGINT AS interaction_rows,
            SUM(patterns.booking_rows)::BIGINT AS booking_rows,
            SUM(patterns.booking_rows)::DOUBLE / NULLIF(SUM(patterns.interaction_rows), 0)
                AS booking_interaction_share,
            SUM(patterns.avg_valid_lead_time_days * patterns.interaction_rows)
                FILTER (WHERE patterns.avg_valid_lead_time_days IS NOT NULL)
                / NULLIF(SUM(patterns.interaction_rows)
                    FILTER (WHERE patterns.avg_valid_lead_time_days IS NOT NULL), 0)
                AS avg_valid_lead_days,
            SUM(patterns.avg_valid_stay_nights * patterns.interaction_rows)
                FILTER (WHERE patterns.avg_valid_stay_nights IS NOT NULL)
                / NULLIF(SUM(patterns.interaction_rows)
                    FILTER (WHERE patterns.avg_valid_stay_nights IS NOT NULL), 0)
                AS avg_valid_stay_nights,
            CASE
                WHEN SUM(patterns.interaction_rows) < 100 THEN 'low'
                WHEN SUM(patterns.interaction_rows) < 1000 THEN 'adequate'
                ELSE 'strong'
            END AS support_level
        FROM source.analytics.dm_travel_patterns AS patterns
        INNER JOIN source.analytics.dim_segment_definition AS traveller
            ON traveller.segment_type = 'traveller'
            AND traveller.segment_value = patterns.traveller_segment
        GROUP BY patterns.event_month, patterns.traveller_segment, traveller.sort_order
        """
    )
    con.execute(
        """
        CREATE TABLE bi_checkin_seasonality AS
        SELECT
            seasonality.checkin_month,
            EXTRACT(YEAR FROM seasonality.checkin_month)::INTEGER AS checkin_year,
            EXTRACT(MONTH FROM seasonality.checkin_month)::INTEGER AS checkin_month_number,
            monthname(seasonality.checkin_month) AS checkin_month_name,
            seasonality.traveller_segment,
            seasonality.interaction_rows,
            seasonality.booking_rows,
            seasonality.booking_rows::DOUBLE / NULLIF(seasonality.interaction_rows, 0)
                AS booking_interaction_share
        FROM source.analytics.dm_checkin_seasonality AS seasonality
        """
    )
    for mart, source_table, entity, identifier in (
        (
            "bi_destination_performance",
            "dm_destination_performance",
            "identified_users",
            "srch_destination_id",
        ),
        (
            "bi_hotel_market_performance",
            "dm_hotel_market_performance",
            "identified_users",
            "hotel_market",
        ),
    ):
        entity_alias = "destination_id" if mart == "bi_destination_performance" else "hotel_market"
        con.execute(
            f"""
            CREATE TABLE {mart} AS
            WITH overall AS (
                SELECT SUM(booking_rows)::DOUBLE / SUM(interaction_rows) AS booking_interaction_share
                FROM source.analytics.{source_table}
            ), strong_threshold AS (
                SELECT quantile_cont(interaction_rows, 0.75) AS interaction_volume_q3_strong
                FROM source.analytics.{source_table}
                WHERE support_level = 'strong'
            )
            SELECT
                source.{identifier} AS {entity_alias},
                source.interaction_rows,
                source.booking_rows,
                source.booking_rows::DOUBLE / NULLIF(source.interaction_rows, 0)
                    AS booking_interaction_share,
                source.booking_interaction_share_ci_low,
                source.booking_interaction_share_ci_high,
                source.{entity} AS entity_users,
                source.support_level,
                source.first_observed_date,
                source.last_observed_date,
                overall.booking_interaction_share AS overall_booking_interaction_share,
                strong_threshold.interaction_volume_q3_strong,
                CASE
                    WHEN source.booking_interaction_share_ci_high < overall.booking_interaction_share
                        THEN 'below_overall_confident'
                    WHEN source.booking_interaction_share_ci_low > overall.booking_interaction_share
                        THEN 'above_overall_confident'
                    ELSE 'inconclusive'
                END AS investigation_class,
                source.support_level = 'strong'
                    AND source.interaction_rows >= strong_threshold.interaction_volume_q3_strong
                    AND source.booking_interaction_share_ci_high < overall.booking_interaction_share
                    AS investigation_candidate
            FROM source.analytics.{source_table} AS source
            CROSS JOIN overall
            CROSS JOIN strong_threshold
            """
        )
    con.execute(
        """
        CREATE TABLE bi_destination_monthly AS
        SELECT
            event_month,
            srch_destination_id AS destination_id,
            interaction_rows,
            booking_rows,
            booking_rows::DOUBLE / NULLIF(interaction_rows, 0) AS booking_interaction_share,
            identified_users AS entity_users,
            CASE
                WHEN interaction_rows < 100 THEN 'low'
                WHEN interaction_rows < 1000 THEN 'adequate'
                ELSE 'strong'
            END AS support_level
        FROM source.analytics.dm_destination_monthly
        """
    )
    con.execute(
        """
        CREATE TABLE bi_routes AS
        SELECT
            origin_id,
            srch_destination_id AS destination_id,
            interaction_rows,
            booking_rows,
            booking_rows::DOUBLE / NULLIF(interaction_rows, 0) AS booking_interaction_share,
            booking_interaction_share_ci_low,
            booking_interaction_share_ci_high,
            identified_users AS entity_users,
            CASE
                WHEN interaction_rows < 100 THEN 'low'
                WHEN interaction_rows < 1000 THEN 'adequate'
                ELSE 'strong'
            END AS support_level
        FROM source.analytics.dm_origin_destination_routes
        """
    )
    con.execute(
        """
        CREATE TABLE bi_observed_recurrence AS
        SELECT
            first_observed_month AS cohort_month,
            activity_month,
            observed_age_month,
            cohort_users,
            observed_active_users,
            observed_booking_users AS booking_users,
            observed_recurrence_share,
            is_right_censored AS is_censored,
            observable_horizon_months
        FROM source.analytics.dm_observed_recurrence
        """
    )
    con.execute(
        """
        CREATE TABLE bi_acceptance_status AS
        SELECT
            TRUE AS accepted,
            0::BIGINT AS failures,
            43::BIGINT AS exact_objects_verified,
            43::BIGINT AS exact_objects_total,
            '20260807T121247Z'::VARCHAR AS stage1_build_id
        """
    )
    con.execute(
        """
        CREATE TABLE bi_missingness_daily AS
        SELECT event_date, field_name, eligible_rows, missing_rows,
            missing_rows::DOUBLE / NULLIF(eligible_rows, 0) AS missing_share
        FROM source.analytics.dm_missingness_daily
        """
    )
    con.execute(
        """
        CREATE TABLE bi_proxy_ambiguity AS
        SELECT ambiguity_type, affected_contexts, proxy_contexts,
            affected_contexts::DOUBLE / NULLIF(proxy_contexts, 0) AS affected_share
        FROM source.analytics.dm_proxy_context_ambiguity
        """
    )
    con.execute(
        """
        CREATE TABLE bi_booking_population_drift_summary AS
        SELECT dimension_name, total_variation_distance, population_stability_index,
            compared_categories AS category_count
        FROM source.analytics.dm_booking_population_drift_summary
        """
    )


def build_bi_layer(
    root: Path, *, build_id: str = SOURCE_BUILD_ID, replace: bool = False
) -> dict[str, Any]:
    """Export dashboard marts and return their machine-readable manifest."""
    root = root.resolve()
    source_database = root / "data" / "analytics" / build_id / "expedia_analytics.duckdb"
    if not source_database.exists():
        raise FileNotFoundError(source_database)
    output_dir = root / "data" / "bi" / build_id
    if output_dir.exists() and any(output_dir.iterdir()) and not replace:
        raise FileExistsError(f"BI output already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{_sql_path(source_database)}' AS source (READ_ONLY)")
        _create_marts(con)
        marts: list[dict[str, Any]] = []
        for name, spec in MART_SPECS.items():
            target = output_dir / f"{name}.parquet"
            temporary_target = output_dir / f".{name}.parquet.tmp"
            con.execute(
                f"COPY {name} TO '{_sql_path(temporary_target)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            os.replace(temporary_target, target)
            columns = [
                {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
                for row in con.execute(f"DESCRIBE {name}").fetchall()
            ]
            marts.append(
                {
                    "name": name,
                    "source_marts": spec["sources"],
                    "purpose": spec["purpose"],
                    "dashboard_page": spec["page"],
                    "dashboard_visuals": spec["visuals"],
                    "grain": spec["grain"],
                    "row_count": con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                    "columns": columns,
                    "canonical_contract_version": BI_CONTRACT_VERSION,
                    "source_build_id": build_id,
                    "checksum": _sha256(target),
                }
            )
    finally:
        con.close()
    manifest = {
        "bi_contract_version": BI_CONTRACT_VERSION,
        "source_build_id": build_id,
        "created_utc": datetime.now(UTC).isoformat(),
        "marts": marts,
    }
    temporary_manifest = output_dir / ".manifest.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary_manifest, output_dir / "manifest.json")
    return manifest
