from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MartSpec:
    name: str
    sql_file: str
    grain: str
    description: str
    date_column: str | None = None
    export_parquet: bool = True


MART_SPECS: tuple[MartSpec, ...] = (
    MartSpec(
        "fct_hotel_interactions",
        "10_fct_hotel_interactions.sql",
        "one aggregated Expedia interaction row",
        "Typed event-level fact with reproducible derived features and quality flags.",
        "event_date",
    ),
    MartSpec(
        "fct_search_contexts",
        "11_fct_search_contexts.sql",
        "one search-context proxy",
        "Search-level proxy aggregated from interactions sharing one user and search request.",
        "event_date",
    ),
    MartSpec(
        "dim_date",
        "20_dim_date.sql",
        "one calendar date",
        "Calendar dimension covering the observed event period.",
        "date_day",
    ),
    MartSpec(
        "dim_destination",
        "21_dim_destination.sql",
        "one search destination",
        "Destination dimension with latent d1-d149 features and observed geography.",
    ),
    MartSpec(
        "dim_user_first_seen",
        "22_dim_user_first_seen.sql",
        "one user",
        "First observed activity date and month for lifecycle segmentation.",
        "first_event_date",
    ),
    MartSpec(
        "dm_product_daily",
        "30_dm_product_daily.sql",
        "one event date",
        "Daily product health metrics based on search-context proxies.",
        "event_date",
    ),
    MartSpec(
        "dm_product_monthly",
        "31_dm_product_monthly.sql",
        "one event month",
        "Monthly product health metrics with correct distinct-user aggregation.",
        "event_month",
    ),
    MartSpec(
        "dm_segment_daily",
        "32_dm_segment_daily.sql",
        "date x segment type x segment value",
        "Long-format daily segment mart for device, package, traveller and other cuts.",
        "event_date",
    ),
    MartSpec(
        "dm_segment_monthly",
        "33_dm_segment_monthly.sql",
        "month x segment type x segment value",
        "Long-format monthly segment mart for stable dashboard queries.",
        "event_month",
    ),
    MartSpec(
        "dm_destination_performance",
        "34_dm_destination_performance.sql",
        "one search destination",
        "Demand, booking-rate and opportunity classification by destination.",
    ),
    MartSpec(
        "dm_destination_monthly",
        "35_dm_destination_monthly.sql",
        "month x search destination",
        "Destination demand and booking dynamics over time.",
        "event_month",
    ),
    MartSpec(
        "dm_travel_patterns",
        "36_dm_travel_patterns.sql",
        "month x traveller x lead time x stay x device x package",
        "Behavioural cube for trip-pattern analysis.",
        "event_month",
    ),
    MartSpec(
        "dm_user_profile",
        "37_dm_user_profile.sql",
        "one user",
        "User-level behavioural profile and lifecycle classification.",
        "first_event_date",
    ),
    MartSpec(
        "dm_user_cohort_monthly",
        "38_dm_user_cohort_monthly.sql",
        "cohort month x activity month",
        "Monthly cohort activity and booking-context rate.",
        "activity_month",
    ),
    MartSpec(
        "dm_data_quality_summary",
        "39_dm_data_quality_summary.sql",
        "one quality rule",
        "Long-format data-quality report with affected rows and severity.",
    ),
    MartSpec(
        "dm_data_quality_daily",
        "40_dm_data_quality_daily.sql",
        "one event date",
        "Daily data-quality monitoring for critical fields and date logic.",
        "event_date",
    ),
)
