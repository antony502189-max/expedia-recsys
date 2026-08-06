from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    name: str
    sql_type: str
    nullable: bool = True
    domain_sql: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectSpec:
    name: str
    layer: str
    grain: tuple[str, ...]
    description: str
    export: bool = True
    partition_by: tuple[str, ...] = ()


TRAIN_COLUMNS: Final[tuple[ColumnSpec, ...]] = (
    ColumnSpec("date_time", "TIMESTAMP", nullable=False),
    ColumnSpec("site_name", "SMALLINT"),
    ColumnSpec("posa_continent", "SMALLINT"),
    ColumnSpec("user_location_country", "INTEGER"),
    ColumnSpec("user_location_region", "INTEGER"),
    ColumnSpec("user_location_city", "INTEGER"),
    ColumnSpec("orig_destination_distance", "DOUBLE"),
    ColumnSpec("user_id", "BIGINT"),
    ColumnSpec("is_mobile", "TINYINT", domain_sql="{value} IN (0, 1)"),
    ColumnSpec("is_package", "TINYINT", domain_sql="{value} IN (0, 1)"),
    ColumnSpec("channel", "SMALLINT"),
    ColumnSpec("srch_ci", "DATE"),
    ColumnSpec("srch_co", "DATE"),
    ColumnSpec("srch_adults_cnt", "SMALLINT"),
    ColumnSpec("srch_children_cnt", "SMALLINT"),
    ColumnSpec("srch_rm_cnt", "SMALLINT"),
    ColumnSpec("srch_destination_id", "INTEGER"),
    ColumnSpec("srch_destination_type_id", "SMALLINT"),
    ColumnSpec("is_booking", "TINYINT", nullable=False, domain_sql="{value} IN (0, 1)"),
    ColumnSpec("cnt", "INTEGER"),
    ColumnSpec("hotel_continent", "SMALLINT"),
    ColumnSpec("hotel_country", "INTEGER"),
    ColumnSpec("hotel_market", "INTEGER"),
    ColumnSpec("hotel_cluster", "SMALLINT", domain_sql="{value} BETWEEN 0 AND 99"),
)

TEST_COLUMNS: Final[tuple[ColumnSpec, ...]] = (
    ColumnSpec("id", "BIGINT", nullable=False),
    ColumnSpec("date_time", "TIMESTAMP", nullable=False),
    ColumnSpec("site_name", "SMALLINT"),
    ColumnSpec("posa_continent", "SMALLINT"),
    ColumnSpec("user_location_country", "INTEGER"),
    ColumnSpec("user_location_region", "INTEGER"),
    ColumnSpec("user_location_city", "INTEGER"),
    ColumnSpec("orig_destination_distance", "DOUBLE"),
    ColumnSpec("user_id", "BIGINT"),
    ColumnSpec("is_mobile", "TINYINT", domain_sql="{value} IN (0, 1)"),
    ColumnSpec("is_package", "TINYINT", domain_sql="{value} IN (0, 1)"),
    ColumnSpec("channel", "SMALLINT"),
    ColumnSpec("srch_ci", "DATE"),
    ColumnSpec("srch_co", "DATE"),
    ColumnSpec("srch_adults_cnt", "SMALLINT"),
    ColumnSpec("srch_children_cnt", "SMALLINT"),
    ColumnSpec("srch_rm_cnt", "SMALLINT"),
    ColumnSpec("srch_destination_id", "INTEGER"),
    ColumnSpec("srch_destination_type_id", "SMALLINT"),
    ColumnSpec("hotel_continent", "SMALLINT"),
    ColumnSpec("hotel_country", "INTEGER"),
    ColumnSpec("hotel_market", "INTEGER"),
)

DESTINATION_COLUMNS: Final[tuple[ColumnSpec, ...]] = (
    ColumnSpec("srch_destination_id", "INTEGER", nullable=False),
    *(ColumnSpec(f"d{index}", "DOUBLE") for index in range(1, 150)),
)

PUBLISHED_OBJECTS: Final[tuple[ObjectSpec, ...]] = (
    ObjectSpec(
        "stg_train_accepted",
        "staging",
        ("raw_row_fingerprint", "duplicate_occurrence"),
        "All type-valid train rows; every raw row is either accepted or quarantined.",
        partition_by=("event_year", "event_month_num"),
    ),
    ObjectSpec(
        "quarantine_train",
        "staging",
        ("raw_row_fingerprint", "duplicate_occurrence"),
        "Rejected train rows with raw values and explicit reject reasons.",
    ),
    ObjectSpec(
        "stg_test_accepted",
        "staging",
        ("id",),
        "Type-valid test booking-population rows, isolated from product outcome marts.",
    ),
    ObjectSpec(
        "quarantine_test",
        "staging",
        ("raw_row_fingerprint", "duplicate_occurrence"),
        "Rejected test rows with explicit reasons.",
    ),
    ObjectSpec(
        "stg_destinations_accepted",
        "staging",
        ("srch_destination_id",),
        "Type-valid latent destination features.",
    ),
    ObjectSpec(
        "quarantine_destinations",
        "staging",
        ("raw_row_fingerprint", "duplicate_occurrence"),
        "Rejected destination rows.",
    ),
    ObjectSpec(
        "fct_hotel_interactions",
        "core",
        ("interaction_id",),
        "One accepted logged click/booking interaction, not one search or session.",
        partition_by=("event_year", "event_month_num"),
    ),
    ObjectSpec(
        "fct_proxy_search_contexts",
        "core",
        ("proxy_context_id",),
        "Deterministic request-like proxy for identified users only.",
        partition_by=("event_year", "event_month_num"),
    ),
    ObjectSpec(
        "fct_user_day",
        "core",
        ("user_id", "event_date"),
        "Robust identified user by observed event day fact.",
        partition_by=("event_year", "event_month_num"),
    ),
    ObjectSpec("dim_date", "dimension", ("date_day",), "Continuous observed date spine."),
    ObjectSpec(
        "dim_origin",
        "dimension",
        ("origin_id",),
        "Composite anonymized user-origin code dimension.",
    ),
    ObjectSpec(
        "dim_destination",
        "dimension",
        ("srch_destination_id",),
        "Anonymized destination dimension with latent d1-d149 features.",
    ),
    ObjectSpec(
        "bridge_destination_hotel_market",
        "bridge",
        ("srch_destination_id", "hotel_market"),
        "Observed many-to-many destination to hotel-market relationship.",
    ),
    ObjectSpec(
        "dim_segment_definition",
        "dimension",
        ("segment_type", "segment_value"),
        "Stable BI labels and ordering for all published segments.",
    ),
    ObjectSpec(
        "dm_sample_activity_daily",
        "mart",
        ("event_date",),
        "Daily coverage and activity of the supplied historical sample.",
    ),
    ObjectSpec(
        "dm_sample_activity_monthly",
        "mart",
        ("event_month",),
        "Monthly coverage and activity of the supplied sample.",
    ),
    ObjectSpec(
        "dm_interaction_outcome_daily",
        "mart",
        ("event_date",),
        "Daily booking share among logged click/booking interactions.",
    ),
    ObjectSpec(
        "dm_interaction_outcome_monthly",
        "mart",
        ("event_month",),
        "Monthly booking share among logged interactions.",
    ),
    ObjectSpec(
        "dm_proxy_context_daily",
        "mart",
        ("event_date",),
        "Secondary sensitivity metric on identified-user proxy contexts.",
    ),
    ObjectSpec(
        "dm_proxy_context_monthly",
        "mart",
        ("event_month",),
        "Monthly proxy-context sensitivity metric and coverage.",
    ),
    ObjectSpec(
        "dm_user_day_daily",
        "mart",
        ("event_date",),
        "Daily identified-user activity and booking-user share.",
    ),
    ObjectSpec(
        "dm_user_day_monthly",
        "mart",
        ("event_month",),
        "Monthly identified-user activity and booking-user share.",
    ),
    ObjectSpec(
        "dm_segment_daily",
        "mart",
        ("event_date", "segment_type", "segment_value"),
        "BI-safe long-format daily segments with additive numerators and denominators.",
    ),
    ObjectSpec(
        "dm_segment_monthly",
        "mart",
        ("event_month", "segment_type", "segment_value"),
        "BI-safe long-format monthly segments.",
    ),
    ObjectSpec(
        "dm_destination_performance",
        "mart",
        ("srch_destination_id",),
        "Destination interaction outcomes with support and Wilson uncertainty.",
    ),
    ObjectSpec(
        "dm_destination_monthly",
        "mart",
        ("event_month", "srch_destination_id"),
        "Monthly destination outcomes with additive components.",
    ),
    ObjectSpec(
        "dm_hotel_market_performance",
        "mart",
        ("hotel_market",),
        "Hotel-market interaction outcomes with uncertainty.",
    ),
    ObjectSpec(
        "dm_origin_destination_routes",
        "mart",
        ("origin_id", "srch_destination_id"),
        "Observed anonymized route demand and interaction outcome.",
    ),
    ObjectSpec(
        "dm_travel_patterns",
        "mart",
        ("event_month", "traveller_segment", "lead_time_segment", "stay_segment"),
        "Travel-pattern cube using only valid trip dates.",
    ),
    ObjectSpec(
        "dm_checkin_seasonality",
        "mart",
        ("checkin_month", "traveller_segment"),
        "Observed interaction outcomes by check-in month and traveller type.",
    ),
    ObjectSpec(
        "dm_booking_window",
        "mart",
        ("lead_time_segment", "stay_segment"),
        "Outcome by valid planning horizon and stay duration.",
    ),
    ObjectSpec(
        "dm_observed_recurrence",
        "mart",
        ("first_observed_month", "activity_month"),
        "Observed recurrence, explicitly not registration-based retention.",
    ),
    ObjectSpec(
        "dm_missingness_daily",
        "mart",
        ("event_date", "field_name"),
        "Missingness and validity drift by event day.",
    ),
    ObjectSpec(
        "dm_proxy_context_ambiguity",
        "mart",
        ("ambiguity_type",),
        "Coverage and ambiguity diagnostics for proxy contexts.",
    ),
    ObjectSpec(
        "dm_booking_population_drift",
        "mart",
        ("dataset", "period_month", "dimension_name", "dimension_value"),
        "Train-booking versus test-booking population drift, not total-product trend.",
    ),
    ObjectSpec(
        "dm_booking_population_drift_summary",
        "mart",
        ("dimension_name",),
        "Distribution drift summary between train and test booking populations.",
    ),
    ObjectSpec(
        "dm_data_quality_summary",
        "mart",
        ("quality_rule",),
        "Source, staging and semantic quality summary.",
    ),
)

PROHIBITED_PUBLIC_TERMS: Final[tuple[str, ...]] = (
    "conversion",
    "retention",
    "revenue",
    "gmv",
    "ctr",
    "churn",
)
