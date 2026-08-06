SELECT
    event_month,
    srch_destination_id,
    MODE(srch_destination_type_id) AS destination_type_id,
    MODE(primary_hotel_country) AS primary_hotel_country,
    MODE(primary_hotel_market) AS primary_hotel_market,
    COUNT(*)::BIGINT AS search_contexts,
    COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_contexts,
    COUNT(*) FILTER (WHERE has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
    COUNT(DISTINCT user_id)::BIGINT AS unique_users,
    SUM(weighted_interactions)::BIGINT AS weighted_interactions,
    COUNT(*) >= 100 AS is_stable_sample
FROM analytics.fct_search_contexts
WHERE srch_destination_id IS NOT NULL
GROUP BY event_month, srch_destination_id
ORDER BY event_month, search_contexts DESC
