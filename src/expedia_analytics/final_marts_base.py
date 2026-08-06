from __future__ import annotations

from typing import Any

from expedia_analytics.final_core import _rate_select


def _create_base_marts(con: Any, contract: dict[str, Any]) -> None:
    minimum = int(contract["support_thresholds"]["minimum_interactions"])
    strong = int(contract["support_thresholds"]["strong_interactions"])
    con.execute(
        f"""
        CREATE TABLE analytics.dm_sample_activity_daily AS
        SELECT
            event_date,
            COUNT(*)::BIGINT AS logged_interaction_rows,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            COUNT(*) FILTER (WHERE user_id IS NULL)::BIGINT AS anonymous_interaction_rows,
            safe_rate(COUNT(*) FILTER (WHERE user_id IS NOT NULL), COUNT(*))
                AS identified_user_coverage,
            COUNT(DISTINCT srch_destination_id)::BIGINT AS observed_destinations,
            COUNT(DISTINCT hotel_market)::BIGINT AS observed_hotel_markets,
            COUNT(*) FILTER (WHERE is_mobile = 1)::BIGINT AS mobile_interaction_rows,
            COUNT(*) FILTER (WHERE is_package = 1)::BIGINT AS package_interaction_rows
        FROM analytics.fct_hotel_interactions
        GROUP BY event_date
        ORDER BY event_date;

        CREATE TABLE analytics.dm_sample_activity_monthly AS
        SELECT
            event_month,
            COUNT(*)::BIGINT AS logged_interaction_rows,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            COUNT(*) FILTER (WHERE user_id IS NULL)::BIGINT AS anonymous_interaction_rows,
            safe_rate(COUNT(*) FILTER (WHERE user_id IS NOT NULL), COUNT(*))
                AS identified_user_coverage,
            COUNT(DISTINCT srch_destination_id)::BIGINT AS observed_destinations,
            COUNT(DISTINCT hotel_market)::BIGINT AS observed_hotel_markets
        FROM analytics.fct_hotel_interactions
        GROUP BY event_month
        ORDER BY event_month;

        CREATE TABLE analytics.dm_interaction_outcome_daily AS
        SELECT event_date, {_rate_select()}
        FROM analytics.fct_hotel_interactions
        GROUP BY event_date
        ORDER BY event_date;

        CREATE TABLE analytics.dm_interaction_outcome_monthly AS
        SELECT event_month, {_rate_select()}
        FROM analytics.fct_hotel_interactions
        GROUP BY event_month
        ORDER BY event_month;

        CREATE TABLE analytics.dm_proxy_context_daily AS
        SELECT
            event_date,
            COUNT(*)::BIGINT AS proxy_search_contexts,
            COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_bearing_proxy_contexts,
            safe_rate(COUNT(*) FILTER (WHERE has_booking), COUNT(*))
                AS booking_bearing_proxy_context_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            SUM(interaction_rows)::BIGINT AS covered_interaction_rows,
            safe_rate(SUM(interaction_rows), (
                SELECT COUNT(*) FROM analytics.fct_hotel_interactions i
                WHERE i.event_date = p.event_date
            )) AS proxy_interaction_coverage
        FROM analytics.fct_proxy_search_contexts p
        GROUP BY event_date
        ORDER BY event_date;

        CREATE TABLE analytics.dm_proxy_context_monthly AS
        SELECT
            event_month,
            COUNT(*)::BIGINT AS proxy_search_contexts,
            COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_bearing_proxy_contexts,
            safe_rate(COUNT(*) FILTER (WHERE has_booking), COUNT(*))
                AS booking_bearing_proxy_context_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            SUM(interaction_rows)::BIGINT AS covered_interaction_rows,
            safe_rate(SUM(interaction_rows), (
                SELECT COUNT(*) FROM analytics.fct_hotel_interactions i
                WHERE i.event_month = p.event_month
            )) AS proxy_interaction_coverage
        FROM analytics.fct_proxy_search_contexts p
        GROUP BY event_month
        ORDER BY event_month;

        CREATE TABLE analytics.dm_user_day_daily AS
        SELECT
            event_date,
            COUNT(*)::BIGINT AS identified_user_days,
            COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_user_days,
            safe_rate(COUNT(*) FILTER (WHERE has_booking), COUNT(*))
                AS booking_user_day_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            SUM(interaction_rows)::BIGINT AS covered_interaction_rows,
            SUM(proxy_contexts)::BIGINT AS proxy_search_contexts
        FROM analytics.fct_user_day
        GROUP BY event_date
        ORDER BY event_date;

        CREATE TABLE analytics.dm_user_day_monthly AS
        SELECT
            event_month,
            COUNT(DISTINCT user_id)::BIGINT AS identified_active_users,
            COUNT(DISTINCT user_id) FILTER (WHERE has_booking)::BIGINT AS booking_users,
            safe_rate(
                COUNT(DISTINCT user_id) FILTER (WHERE has_booking),
                COUNT(DISTINCT user_id)
            ) AS booking_user_share,
            COUNT(*)::BIGINT AS identified_user_days,
            SUM(interaction_rows)::BIGINT AS covered_interaction_rows,
            SUM(proxy_contexts)::BIGINT AS proxy_search_contexts
        FROM analytics.fct_user_day
        GROUP BY event_month
        ORDER BY event_month;
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dm_segment_daily AS
        WITH long_form AS (
            SELECT event_date, is_booking, 'device' AS segment_type,
                   device_segment AS segment_value
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'package', package_segment
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'traveller', traveller_segment
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'lead_time', lead_time_segment
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'stay', stay_segment
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'channel', COALESCE(channel::VARCHAR, 'missing')
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, is_booking, 'site', COALESCE(site_name::VARCHAR, 'missing')
            FROM analytics.fct_hotel_interactions
        )
        SELECT
            event_date,
            segment_type,
            segment_value,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share
        FROM long_form
        GROUP BY event_date, segment_type, segment_value;

        CREATE TABLE analytics.dm_segment_monthly AS
        SELECT
            DATE_TRUNC('month', event_date)::DATE AS event_month,
            segment_type,
            segment_value,
            SUM(interaction_rows)::BIGINT AS interaction_rows,
            SUM(booking_rows)::BIGINT AS booking_rows,
            safe_rate(SUM(booking_rows), SUM(interaction_rows)) AS booking_interaction_share
        FROM analytics.dm_segment_daily
        GROUP BY event_month, segment_type, segment_value;
        """
    )
    for table, key in (
        ("dm_destination_performance", "srch_destination_id"),
        ("dm_hotel_market_performance", "hotel_market"),
    ):
        con.execute(
            f"""
            CREATE TABLE analytics.{table} AS
            SELECT
                {key},
                {_rate_select()},
                COUNT(DISTINCT user_id)::BIGINT AS identified_users,
                MIN(event_date) AS first_observed_date,
                MAX(event_date) AS last_observed_date,
                CASE
                    WHEN COUNT(*) >= {strong} THEN 'strong'
                    WHEN COUNT(*) >= {minimum} THEN 'adequate'
                    ELSE 'low'
                END AS support_level
            FROM analytics.fct_hotel_interactions
            WHERE {key} IS NOT NULL
            GROUP BY {key};
            """
        )
    con.execute(
        """
        CREATE TABLE analytics.dm_destination_monthly AS
        SELECT
            event_month,
            srch_destination_id,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_users
        FROM analytics.fct_hotel_interactions
        WHERE srch_destination_id IS NOT NULL
        GROUP BY event_month, srch_destination_id;
        """
    )
    con.execute(
        f"""
        CREATE TABLE analytics.dm_origin_destination_routes AS
        SELECT
            origin_id,
            srch_destination_id,
            {_rate_select()},
            COUNT(DISTINCT user_id)::BIGINT AS identified_users,
            CASE
                WHEN COUNT(*) >= {strong} THEN 'strong'
                WHEN COUNT(*) >= {minimum} THEN 'adequate'
                ELSE 'low'
            END AS support_level
        FROM analytics.fct_hotel_interactions
        WHERE srch_destination_id IS NOT NULL
        GROUP BY origin_id, srch_destination_id;

        CREATE TABLE analytics.dm_travel_patterns AS
        SELECT
            event_month,
            traveller_segment,
            lead_time_segment,
            stay_segment,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_users,
            AVG(lead_time_days) FILTER (WHERE has_valid_lead_time) AS avg_valid_lead_time_days,
            MEDIAN(lead_time_days) FILTER (WHERE has_valid_lead_time)
                AS median_valid_lead_time_days,
            AVG(stay_nights) FILTER (WHERE has_valid_stay_dates) AS avg_valid_stay_nights,
            CASE
                WHEN COUNT(*) >= {strong} THEN 'strong'
                WHEN COUNT(*) >= {minimum} THEN 'adequate'
                ELSE 'low'
            END AS support_level
        FROM analytics.fct_hotel_interactions
        GROUP BY event_month, traveller_segment, lead_time_segment, stay_segment;
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dm_checkin_seasonality AS
        SELECT
            DATE_TRUNC('month', checkin_date)::DATE AS checkin_month,
            traveller_segment,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share,
            COUNT(DISTINCT user_id)::BIGINT AS identified_users
        FROM analytics.fct_hotel_interactions
        WHERE checkin_date IS NOT NULL AND has_valid_lead_time
        GROUP BY checkin_month, traveller_segment;

        CREATE TABLE analytics.dm_booking_window AS
        SELECT
            lead_time_segment,
            stay_segment,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share,
            wilson_low(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share_ci_low,
            wilson_high(COUNT(*) FILTER (WHERE is_booking = 1), COUNT(*))
                AS booking_interaction_share_ci_high
        FROM analytics.fct_hotel_interactions
        WHERE has_valid_lead_time AND has_valid_stay_dates
        GROUP BY lead_time_segment, stay_segment;
        """
    )
