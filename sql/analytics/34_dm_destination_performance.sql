WITH aggregated AS (
    SELECT
        srch_destination_id,
        MODE(srch_destination_type_id) AS destination_type_id,
        MODE(primary_hotel_continent) AS primary_hotel_continent,
        MODE(primary_hotel_country) AS primary_hotel_country,
        MODE(primary_hotel_market) AS primary_hotel_market,
        COUNT(*)::BIGINT AS search_contexts,
        COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_contexts,
        COUNT(*) FILTER (WHERE has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
        COUNT(DISTINCT user_id)::BIGINT AS unique_users,
        SUM(interaction_rows)::BIGINT AS interaction_rows,
        SUM(weighted_interactions)::BIGINT AS weighted_interactions,
        AVG(lead_time_days) FILTER (WHERE has_valid_lead_time) AS avg_lead_time_days,
        AVG(stay_nights) FILTER (WHERE has_valid_stay_dates) AS avg_stay_nights,
        COUNT(*) FILTER (WHERE device_segment = 'mobile')::DOUBLE / NULLIF(COUNT(*), 0) AS mobile_context_share,
        COUNT(*) FILTER (WHERE package_segment = 'package')::DOUBLE / NULLIF(COUNT(*), 0) AS package_context_share,
        MIN(event_date) AS first_seen_date,
        MAX(event_date) AS last_seen_date
    FROM analytics.fct_search_contexts
    WHERE srch_destination_id IS NOT NULL
    GROUP BY srch_destination_id
), ranked AS (
    SELECT
        *,
        NTILE(10) OVER (ORDER BY search_contexts) AS demand_decile,
        NTILE(10) OVER (ORDER BY booking_context_rate) AS booking_rate_decile,
        MEDIAN(search_contexts) OVER () AS median_destination_demand,
        MEDIAN(booking_context_rate) OVER () AS median_destination_booking_rate
    FROM aggregated
)
SELECT
    *,
    CASE
        WHEN search_contexts >= median_destination_demand
         AND booking_context_rate >= median_destination_booking_rate
            THEN 'high_demand_high_rate'
        WHEN search_contexts >= median_destination_demand
         AND booking_context_rate < median_destination_booking_rate
            THEN 'high_demand_low_rate'
        WHEN search_contexts < median_destination_demand
         AND booking_context_rate >= median_destination_booking_rate
            THEN 'low_demand_high_rate'
        ELSE 'low_demand_low_rate'
    END AS performance_quadrant,
    search_contexts >= 100 AS is_stable_sample
FROM ranked
ORDER BY search_contexts DESC
