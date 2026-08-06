SELECT
    user_id,
    MIN(event_date) AS first_event_date,
    MAX(event_date) AS last_event_date,
    DATE_DIFF('day', MIN(event_date), MAX(event_date)) AS observed_lifetime_days,
    COUNT(*)::BIGINT AS search_contexts,
    COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_contexts,
    COUNT(*) FILTER (WHERE has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
    COUNT(DISTINCT event_date)::INTEGER AS active_days,
    COUNT(DISTINCT event_month)::SMALLINT AS active_months,
    SUM(interaction_rows)::BIGINT AS interaction_rows,
    SUM(weighted_interactions)::BIGINT AS weighted_interactions,
    MODE(device_segment) AS preferred_device_segment,
    MODE(package_segment) AS preferred_package_segment,
    MODE(traveller_segment) AS dominant_traveller_segment,
    MODE(srch_destination_id) AS most_frequent_destination_id,
    COUNT(DISTINCT srch_destination_id)::INTEGER AS unique_destinations,
    COUNT(DISTINCT primary_hotel_market)::INTEGER AS unique_hotel_markets,
    AVG(lead_time_days) FILTER (WHERE has_valid_lead_time) AS avg_lead_time_days,
    AVG(stay_nights) FILTER (WHERE has_valid_stay_dates) AS avg_stay_nights,
    CASE
        WHEN COUNT(*) = 1 AND COUNT(*) FILTER (WHERE has_booking) = 0 THEN 'one_time_non_booker'
        WHEN COUNT(*) = 1 AND COUNT(*) FILTER (WHERE has_booking) > 0 THEN 'one_time_booker'
        WHEN COUNT(*) > 1 AND COUNT(*) FILTER (WHERE has_booking) = 0 THEN 'repeat_non_booker'
        WHEN COUNT(*) > 1 AND COUNT(*) FILTER (WHERE has_booking) > 0 THEN 'repeat_booker'
        ELSE 'unknown'
    END AS user_value_segment
FROM analytics.fct_search_contexts
WHERE user_id IS NOT NULL
GROUP BY user_id
