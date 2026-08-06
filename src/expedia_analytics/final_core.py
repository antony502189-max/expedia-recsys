from __future__ import annotations

from typing import Any


def _create_macros(con: Any) -> None:
    con.execute(
        """
        CREATE OR REPLACE MACRO safe_rate(numerator, denominator) AS
            CASE WHEN denominator > 0 THEN numerator::DOUBLE / denominator ELSE NULL END;
        CREATE OR REPLACE MACRO wilson_low(successes, total) AS
            CASE WHEN total > 0 THEN
                ((successes::DOUBLE / total) + 1.9208 / total
                 - 1.96 * SQRT(
                    ((successes::DOUBLE / total) * (1 - successes::DOUBLE / total)
                     + 0.9604 / total) / total
                 )) / (1 + 3.8416 / total)
            ELSE NULL END;
        CREATE OR REPLACE MACRO wilson_high(successes, total) AS
            CASE WHEN total > 0 THEN
                ((successes::DOUBLE / total) + 1.9208 / total
                 + 1.96 * SQRT(
                    ((successes::DOUBLE / total) * (1 - successes::DOUBLE / total)
                     + 0.9604 / total) / total
                 )) / (1 + 3.8416 / total)
            ELSE NULL END;
        """
    )


def _create_core(con: Any, contract: dict[str, Any]) -> None:
    lead = contract["segment_boundaries"]["lead_time_days"]
    stay = contract["segment_boundaries"]["stay_nights"]
    con.execute("CREATE SCHEMA analytics")
    _create_macros(con)
    con.execute(
        f"""
        CREATE TABLE analytics.fct_hotel_interactions AS
        SELECT
            SHA256(CONCAT(raw_row_fingerprint, ':', duplicate_occurrence::VARCHAR))
                AS interaction_id,
            raw_row_fingerprint,
            duplicate_group_size,
            duplicate_occurrence,
            date_time AS event_datetime,
            CAST(date_time AS DATE) AS event_date,
            CAST(DATE_TRUNC('month', date_time) AS DATE) AS event_month,
            EXTRACT(year FROM date_time)::SMALLINT AS event_year,
            EXTRACT(month FROM date_time)::TINYINT AS event_month_num,
            EXTRACT(isodow FROM date_time)::TINYINT AS event_iso_day_of_week,
            site_name,
            posa_continent,
            user_location_country,
            user_location_region,
            user_location_city,
            SHA256(CONCAT_WS('|',
                COALESCE(user_location_country::VARCHAR, '<NULL>'),
                COALESCE(user_location_region::VARCHAR, '<NULL>'),
                COALESCE(user_location_city::VARCHAR, '<NULL>')
            )) AS origin_id,
            orig_destination_distance,
            user_id,
            is_mobile,
            is_package,
            channel,
            srch_ci AS checkin_date,
            srch_co AS checkout_date,
            DATE_DIFF('day', CAST(date_time AS DATE), srch_ci)::INTEGER AS lead_time_days,
            DATE_DIFF('day', srch_ci, srch_co)::INTEGER AS stay_nights,
            srch_adults_cnt,
            srch_children_cnt,
            srch_rm_cnt,
            COALESCE(srch_adults_cnt, 0) + COALESCE(srch_children_cnt, 0)
                AS party_size,
            srch_destination_id,
            srch_destination_type_id,
            is_booking,
            cnt AS similar_event_count,
            cnt IS NOT NULL AND cnt > 0 AS has_valid_similar_event_count,
            CASE WHEN cnt > 0 THEN cnt ELSE NULL END AS valid_similar_event_count,
            hotel_continent,
            hotel_country,
            hotel_market,
            hotel_cluster,
            CASE
                WHEN is_mobile = 1 THEN 'mobile'
                WHEN is_mobile = 0 THEN 'desktop'
                ELSE 'unknown'
            END AS device_segment,
            CASE
                WHEN is_package = 1 THEN 'package'
                WHEN is_package = 0 THEN 'standalone'
                ELSE 'unknown'
            END AS package_segment,
            CASE
                WHEN srch_children_cnt > 0 THEN 'family'
                WHEN srch_adults_cnt = 1 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'solo'
                WHEN srch_adults_cnt = 2 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'couple'
                WHEN srch_adults_cnt >= 3 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'group'
                ELSE 'unknown'
            END AS traveller_segment,
            CASE
                WHEN srch_ci IS NULL THEN 'missing'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) < 0 THEN 'invalid_negative'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) = {lead[0]} THEN 'same_day'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) <= {lead[1]}
                    THEN '01_07_days'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) <= {lead[2]}
                    THEN '08_30_days'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) <= {lead[3]}
                    THEN '31_90_days'
                WHEN DATE_DIFF('day', CAST(date_time AS DATE), srch_ci) <= {lead[4]}
                    THEN '91_180_days'
                ELSE '181_plus_days'
            END AS lead_time_segment,
            CASE
                WHEN srch_ci IS NULL OR srch_co IS NULL THEN 'missing'
                WHEN DATE_DIFF('day', srch_ci, srch_co) <= 0 THEN 'invalid_nonpositive'
                WHEN DATE_DIFF('day', srch_ci, srch_co) <= {stay[0]} THEN '01_night'
                WHEN DATE_DIFF('day', srch_ci, srch_co) <= {stay[1]} THEN '02_03_nights'
                WHEN DATE_DIFF('day', srch_ci, srch_co) <= {stay[2]} THEN '04_07_nights'
                WHEN DATE_DIFF('day', srch_ci, srch_co) <= {stay[3]} THEN '08_14_nights'
                ELSE '15_plus_nights'
            END AS stay_segment,
            srch_ci IS NOT NULL AND srch_ci >= CAST(date_time AS DATE)
                AS has_valid_lead_time,
            srch_ci IS NOT NULL AND srch_co IS NOT NULL AND srch_co > srch_ci
                AS has_valid_stay_dates
        FROM staging.stg_train_accepted
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.fct_proxy_search_contexts AS
        WITH keyed AS (
            SELECT
                *,
                SHA256(CONCAT_WS('|',
                    user_id::VARCHAR,
                    event_datetime::VARCHAR,
                    COALESCE(site_name::VARCHAR, '<NULL>'),
                    COALESCE(origin_id, '<NULL>'),
                    COALESCE(is_mobile::VARCHAR, '<NULL>'),
                    COALESCE(is_package::VARCHAR, '<NULL>'),
                    COALESCE(channel::VARCHAR, '<NULL>'),
                    COALESCE(checkin_date::VARCHAR, '<NULL>'),
                    COALESCE(checkout_date::VARCHAR, '<NULL>'),
                    COALESCE(srch_adults_cnt::VARCHAR, '<NULL>'),
                    COALESCE(srch_children_cnt::VARCHAR, '<NULL>'),
                    COALESCE(srch_rm_cnt::VARCHAR, '<NULL>'),
                    COALESCE(srch_destination_id::VARCHAR, '<NULL>'),
                    COALESCE(srch_destination_type_id::VARCHAR, '<NULL>')
                )) AS proxy_context_id
            FROM analytics.fct_hotel_interactions
            WHERE user_id IS NOT NULL
        )
        SELECT
            proxy_context_id,
            MIN(event_datetime) AS event_datetime,
            MIN(event_date) AS event_date,
            MIN(event_month) AS event_month,
            MIN(event_year)::SMALLINT AS event_year,
            MIN(event_month_num)::TINYINT AS event_month_num,
            ANY_VALUE(user_id) AS user_id,
            ANY_VALUE(origin_id) AS origin_id,
            ANY_VALUE(site_name) AS site_name,
            ANY_VALUE(channel) AS channel,
            ANY_VALUE(device_segment) AS device_segment,
            ANY_VALUE(package_segment) AS package_segment,
            ANY_VALUE(traveller_segment) AS traveller_segment,
            ANY_VALUE(lead_time_segment) AS lead_time_segment,
            ANY_VALUE(stay_segment) AS stay_segment,
            ANY_VALUE(checkin_date) AS checkin_date,
            ANY_VALUE(checkout_date) AS checkout_date,
            ANY_VALUE(lead_time_days) AS lead_time_days,
            ANY_VALUE(stay_nights) AS stay_nights,
            ANY_VALUE(srch_adults_cnt) AS srch_adults_cnt,
            ANY_VALUE(srch_children_cnt) AS srch_children_cnt,
            ANY_VALUE(srch_rm_cnt) AS srch_rm_cnt,
            ANY_VALUE(srch_destination_id) AS srch_destination_id,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 0)::BIGINT AS click_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            BOOL_OR(is_booking = 1) AS has_booking,
            COUNT(DISTINCT hotel_cluster)::INTEGER AS distinct_hotel_clusters,
            COUNT(DISTINCT hotel_market)::INTEGER AS distinct_hotel_markets,
            MIN(orig_destination_distance) AS min_hotel_distance,
            MEDIAN(orig_destination_distance) AS median_hotel_distance,
            MAX(orig_destination_distance) AS max_hotel_distance,
            safe_rate(
                COUNT(*) FILTER (WHERE orig_destination_distance IS NULL), COUNT(*)
            ) AS distance_missing_share,
            MEDIAN(orig_destination_distance) FILTER (WHERE is_booking = 1)
                AS booked_hotel_distance,
            SUM(valid_similar_event_count) AS valid_similar_event_count
        FROM keyed
        GROUP BY proxy_context_id
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.fct_user_day AS
        SELECT
            user_id,
            event_date,
            CAST(DATE_TRUNC('month', event_date) AS DATE) AS event_month,
            EXTRACT(year FROM event_date)::SMALLINT AS event_year,
            EXTRACT(month FROM event_date)::TINYINT AS event_month_num,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            COUNT(DISTINCT srch_destination_id)::BIGINT AS distinct_destinations,
            COUNT(DISTINCT proxy_context_id)::BIGINT AS proxy_contexts,
            BOOL_OR(has_booking) AS has_booking
        FROM analytics.fct_proxy_search_contexts
        GROUP BY user_id, event_date
        """
    )


def _create_dimensions(con: Any) -> None:
    destination_features = ", ".join(f"d{index}" for index in range(1, 150))
    con.execute(
        """
        CREATE TABLE analytics.dim_date AS
        WITH bounds AS (
            SELECT
                LEAST(MIN(event_date), MIN(checkin_date), MIN(checkout_date)) AS min_date,
                GREATEST(MAX(event_date), MAX(checkin_date), MAX(checkout_date)) AS max_date
            FROM analytics.fct_hotel_interactions
        )
        SELECT
            day_value::DATE AS date_day,
            EXTRACT(year FROM day_value)::SMALLINT AS calendar_year,
            EXTRACT(quarter FROM day_value)::TINYINT AS calendar_quarter,
            EXTRACT(month FROM day_value)::TINYINT AS calendar_month,
            EXTRACT(week FROM day_value)::TINYINT AS iso_week,
            EXTRACT(isodow FROM day_value)::TINYINT AS iso_day_of_week,
            EXTRACT(isodow FROM day_value) IN (6, 7) AS is_weekend,
            DATE_TRUNC('week', day_value)::DATE AS week_start,
            DATE_TRUNC('month', day_value)::DATE AS month_start,
            DATE_TRUNC('quarter', day_value)::DATE AS quarter_start,
            DATE_TRUNC('year', day_value)::DATE AS year_start
        FROM bounds,
             GENERATE_SERIES(min_date, max_date, INTERVAL 1 DAY) AS dates(day_value)
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dim_origin AS
        SELECT
            origin_id,
            MIN(user_location_country) AS user_location_country,
            MIN(user_location_region) AS user_location_region,
            MIN(user_location_city) AS user_location_city,
            COUNT(*)::BIGINT AS interaction_rows,
            MIN(event_date) AS first_observed_date,
            MAX(event_date) AS last_observed_date
        FROM analytics.fct_hotel_interactions
        GROUP BY origin_id
        """
    )
    con.execute(
        f"""
        CREATE TABLE analytics.dim_destination AS
        WITH observed AS (
            SELECT
                srch_destination_id,
                MIN(srch_destination_type_id) AS srch_destination_type_id,
                COUNT(*)::BIGINT AS interaction_rows,
                MIN(event_date) AS first_observed_date,
                MAX(event_date) AS last_observed_date
            FROM analytics.fct_hotel_interactions
            WHERE srch_destination_id IS NOT NULL
            GROUP BY srch_destination_id
        )
        SELECT
            d.srch_destination_id,
            o.srch_destination_type_id,
            o.interaction_rows,
            o.first_observed_date,
            o.last_observed_date,
            {destination_features}
        FROM staging.stg_destinations_accepted d
        LEFT JOIN observed o USING (srch_destination_id)
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.bridge_destination_hotel_market AS
        SELECT
            srch_destination_id,
            hotel_market,
            COUNT(*)::BIGINT AS interaction_rows,
            COUNT(*) FILTER (WHERE is_booking = 1)::BIGINT AS booking_rows,
            safe_rate(COUNT(*), SUM(COUNT(*)) OVER (PARTITION BY srch_destination_id))
                AS interaction_share_within_destination,
            MIN(event_date) AS first_observed_date,
            MAX(event_date) AS last_observed_date
        FROM analytics.fct_hotel_interactions
        WHERE srch_destination_id IS NOT NULL AND hotel_market IS NOT NULL
        GROUP BY srch_destination_id, hotel_market
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dim_segment_definition AS
        SELECT * FROM (VALUES
            ('device', 'desktop', 1, 'Desktop logged interaction'),
            ('device', 'mobile', 2, 'Mobile logged interaction'),
            ('device', 'unknown', 99, 'Missing device flag'),
            ('package', 'standalone', 1, 'Non-package trip'),
            ('package', 'package', 2, 'Package trip'),
            ('package', 'unknown', 99, 'Missing package flag'),
            ('traveller', 'solo', 1, 'One adult, no children'),
            ('traveller', 'couple', 2, 'Two adults, no children'),
            ('traveller', 'family', 3, 'At least one child'),
            ('traveller', 'group', 4, 'Three or more adults, no children'),
            ('traveller', 'unknown', 99, 'Unclassified party'),
            ('lead_time', 'same_day', 1, 'Check-in on event date'),
            ('lead_time', '01_07_days', 2, 'One to seven days'),
            ('lead_time', '08_30_days', 3, 'Eight to thirty days'),
            ('lead_time', '31_90_days', 4, 'Thirty-one to ninety days'),
            ('lead_time', '91_180_days', 5, 'Ninety-one to one hundred eighty days'),
            ('lead_time', '181_plus_days', 6, 'More than one hundred eighty days'),
            ('lead_time', 'invalid_negative', 98, 'Check-in before event'),
            ('lead_time', 'missing', 99, 'Missing check-in'),
            ('stay', '01_night', 1, 'One night'),
            ('stay', '02_03_nights', 2, 'Two to three nights'),
            ('stay', '04_07_nights', 3, 'Four to seven nights'),
            ('stay', '08_14_nights', 4, 'Eight to fourteen nights'),
            ('stay', '15_plus_nights', 5, 'Fifteen or more nights'),
            ('stay', 'invalid_nonpositive', 98, 'Checkout not after check-in'),
            ('stay', 'missing', 99, 'Missing stay dates')
        ) AS t(segment_type, segment_value, sort_order, description)
        """
    )


def _rate_select(prefix: str = "") -> str:
    p = prefix
    return f"""
        COUNT(*)::BIGINT AS interaction_rows,
        COUNT(*) FILTER (WHERE {p}is_booking = 0)::BIGINT AS click_rows,
        COUNT(*) FILTER (WHERE {p}is_booking = 1)::BIGINT AS booking_rows,
        safe_rate(COUNT(*) FILTER (WHERE {p}is_booking = 1), COUNT(*))
            AS booking_interaction_share,
        wilson_low(COUNT(*) FILTER (WHERE {p}is_booking = 1), COUNT(*))
            AS booking_interaction_share_ci_low,
        wilson_high(COUNT(*) FILTER (WHERE {p}is_booking = 1), COUNT(*))
            AS booking_interaction_share_ci_high,
        SUM(valid_similar_event_count)::HUGEINT AS valid_similar_event_count,
        SUM(valid_similar_event_count) FILTER (WHERE {p}is_booking = 0)::HUGEINT
            AS weighted_click_events,
        SUM(valid_similar_event_count) FILTER (WHERE {p}is_booking = 1)::HUGEINT
            AS weighted_booking_events,
        safe_rate(
            SUM(valid_similar_event_count) FILTER (WHERE {p}is_booking = 1),
            SUM(valid_similar_event_count)
        ) AS weighted_booking_event_share,
        safe_rate(COUNT(*) FILTER (WHERE valid_similar_event_count IS NOT NULL), COUNT(*))
            AS similar_event_count_coverage
    """
