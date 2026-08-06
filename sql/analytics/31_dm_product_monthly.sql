SELECT
    c.event_month,
    COUNT(*)::BIGINT AS search_contexts,
    COUNT(*) FILTER (WHERE c.has_booking)::BIGINT AS booking_contexts,
    COUNT(*) FILTER (WHERE NOT c.has_booking)::BIGINT AS non_booking_contexts,
    COUNT(*) FILTER (WHERE c.has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
    COUNT(DISTINCT c.user_id)::BIGINT AS active_users,
    COUNT(DISTINCT CASE WHEN c.event_month = u.first_event_month THEN c.user_id END)::BIGINT AS new_users,
    COUNT(DISTINCT CASE WHEN c.event_month > u.first_event_month THEN c.user_id END)::BIGINT AS returning_users,
    SUM(c.interaction_rows)::BIGINT AS interaction_rows,
    SUM(c.weighted_interactions)::BIGINT AS weighted_interactions,
    SUM(c.booking_rows)::BIGINT AS booking_rows,
    SUM(c.weighted_bookings)::BIGINT AS weighted_bookings,
    COUNT(*) FILTER (WHERE c.device_segment = 'mobile')::DOUBLE / NULLIF(COUNT(*), 0) AS mobile_context_share,
    COUNT(*) FILTER (WHERE c.package_segment = 'package')::DOUBLE / NULLIF(COUNT(*), 0) AS package_context_share,
    AVG(c.lead_time_days) FILTER (WHERE c.has_valid_lead_time) AS avg_lead_time_days,
    MEDIAN(c.lead_time_days) FILTER (WHERE c.has_valid_lead_time) AS median_lead_time_days,
    AVG(c.stay_nights) FILTER (WHERE c.has_valid_stay_dates) AS avg_stay_nights,
    MEDIAN(c.stay_nights) FILTER (WHERE c.has_valid_stay_dates) AS median_stay_nights,
    COUNT(DISTINCT c.srch_destination_id)::BIGINT AS unique_destinations,
    COUNT(*)::DOUBLE / NULLIF(COUNT(DISTINCT c.user_id), 0) AS contexts_per_active_user
FROM analytics.fct_search_contexts c
LEFT JOIN analytics.dim_user_first_seen u USING (user_id)
GROUP BY c.event_month
ORDER BY c.event_month
