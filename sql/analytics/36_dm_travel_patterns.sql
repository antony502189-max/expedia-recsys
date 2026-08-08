SELECT
    event_month,
    traveller_segment,
    lead_time_segment,
    stay_segment,
    device_segment,
    package_segment,
    COUNT(*)::BIGINT AS search_contexts,
    COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_contexts,
    COUNT(*) FILTER (WHERE has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
    COUNT(DISTINCT user_id)::BIGINT AS active_users,
    AVG(party_size) AS avg_party_size,
    AVG(srch_rm_cnt) AS avg_rooms,
    AVG(lead_time_days) FILTER (WHERE has_valid_lead_time) AS avg_lead_time_days,
    AVG(stay_nights) FILTER (WHERE has_valid_stay_dates) AS avg_stay_nights,
    SUM(weighted_interactions)::BIGINT AS weighted_interactions,
    COUNT(*) >= 300 AS is_stable_sample
FROM analytics.fct_search_contexts
GROUP BY
    event_month,
    traveller_segment,
    lead_time_segment,
    stay_segment,
    device_segment,
    package_segment
ORDER BY event_month, search_contexts DESC
