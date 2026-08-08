SELECT
    event_date,
    COUNT(*)::BIGINT AS interaction_rows,
    COUNT(*) FILTER (WHERE user_id IS NULL)::BIGINT AS null_user_id_rows,
    COUNT(*) FILTER (WHERE checkin_date IS NULL)::BIGINT AS null_checkin_rows,
    COUNT(*) FILTER (WHERE checkout_date IS NULL)::BIGINT AS null_checkout_rows,
    COUNT(*) FILTER (WHERE lead_time_days < 0)::BIGINT AS negative_lead_time_rows,
    COUNT(*) FILTER (WHERE stay_nights <= 0)::BIGINT AS nonpositive_stay_rows,
    COUNT(*) FILTER (WHERE orig_destination_distance IS NULL)::BIGINT AS missing_distance_rows,
    COUNT(*) FILTER (WHERE srch_destination_id IS NULL)::BIGINT AS missing_destination_rows,
    COUNT(*) FILTER (WHERE source_cnt IS NULL OR source_cnt <= 0)::BIGINT AS invalid_source_cnt_rows,
    COUNT(*) FILTER (WHERE user_id IS NULL)::DOUBLE / NULLIF(COUNT(*), 0) AS null_user_id_rate,
    COUNT(*) FILTER (WHERE lead_time_days < 0)::DOUBLE / NULLIF(COUNT(*), 0) AS negative_lead_time_rate,
    COUNT(*) FILTER (WHERE stay_nights <= 0)::DOUBLE / NULLIF(COUNT(*), 0) AS nonpositive_stay_rate,
    COUNT(*) FILTER (WHERE orig_destination_distance IS NULL)::DOUBLE / NULLIF(COUNT(*), 0) AS missing_distance_rate
FROM analytics.fct_hotel_interactions
GROUP BY event_date
ORDER BY event_date
