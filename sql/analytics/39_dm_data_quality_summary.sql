WITH profile AS (
    SELECT
        COUNT(*)::BIGINT AS total_rows,
        COUNT(*) FILTER (WHERE user_id IS NULL)::BIGINT AS null_user_id,
        COUNT(*) FILTER (WHERE checkin_date IS NULL)::BIGINT AS null_checkin_date,
        COUNT(*) FILTER (WHERE checkout_date IS NULL)::BIGINT AS null_checkout_date,
        COUNT(*) FILTER (WHERE lead_time_days < 0)::BIGINT AS negative_lead_time,
        COUNT(*) FILTER (WHERE stay_nights <= 0)::BIGINT AS nonpositive_stay,
        COUNT(*) FILTER (WHERE orig_destination_distance IS NULL)::BIGINT AS missing_distance,
        COUNT(*) FILTER (WHERE srch_adults_cnt IS NULL OR srch_adults_cnt <= 0)::BIGINT AS invalid_adults,
        COUNT(*) FILTER (WHERE srch_children_cnt < 0)::BIGINT AS invalid_children,
        COUNT(*) FILTER (WHERE srch_rm_cnt IS NULL OR srch_rm_cnt <= 0)::BIGINT AS invalid_rooms,
        COUNT(*) FILTER (WHERE srch_destination_id IS NULL)::BIGINT AS missing_destination,
        COUNT(*) FILTER (WHERE hotel_market IS NULL)::BIGINT AS missing_hotel_market,
        COUNT(*) FILTER (WHERE source_cnt IS NULL OR source_cnt <= 0)::BIGINT AS invalid_source_cnt,
        COUNT(*) FILTER (WHERE is_booking NOT IN (0, 1))::BIGINT AS invalid_booking_flag
    FROM analytics.fct_hotel_interactions
), rules AS (
    SELECT 'source_rows' AS rule_name, total_rows AS affected_rows, total_rows,
           'info' AS severity, 'Total typed interaction rows.' AS rule_description FROM profile
    UNION ALL SELECT 'null_user_id', null_user_id, total_rows, 'warning', 'Rows without a user identifier.' FROM profile
    UNION ALL SELECT 'null_checkin_date', null_checkin_date, total_rows, 'warning', 'Rows without a check-in date.' FROM profile
    UNION ALL SELECT 'null_checkout_date', null_checkout_date, total_rows, 'warning', 'Rows without a check-out date.' FROM profile
    UNION ALL SELECT 'negative_lead_time', negative_lead_time, total_rows, 'warning', 'Check-in precedes the interaction date.' FROM profile
    UNION ALL SELECT 'nonpositive_stay', nonpositive_stay, total_rows, 'warning', 'Checkout is not after check-in.' FROM profile
    UNION ALL SELECT 'missing_distance', missing_distance, total_rows, 'info', 'Origin-destination distance could not be calculated.' FROM profile
    UNION ALL SELECT 'invalid_adults', invalid_adults, total_rows, 'warning', 'Adults count is missing or non-positive.' FROM profile
    UNION ALL SELECT 'invalid_children', invalid_children, total_rows, 'critical', 'Children count is negative.' FROM profile
    UNION ALL SELECT 'invalid_rooms', invalid_rooms, total_rows, 'warning', 'Room count is missing or non-positive.' FROM profile
    UNION ALL SELECT 'missing_destination', missing_destination, total_rows, 'warning', 'Search destination is missing.' FROM profile
    UNION ALL SELECT 'missing_hotel_market', missing_hotel_market, total_rows, 'info', 'Hotel market is missing.' FROM profile
    UNION ALL SELECT 'invalid_source_cnt', invalid_source_cnt, total_rows, 'warning', 'cnt is missing or non-positive; event_weight defaults to one.' FROM profile
    UNION ALL SELECT 'invalid_booking_flag', invalid_booking_flag, total_rows, 'critical', 'is_booking is outside the expected 0/1 domain.' FROM profile
)
SELECT
    rule_name,
    affected_rows,
    total_rows,
    affected_rows::DOUBLE / NULLIF(total_rows, 0) AS affected_rate,
    severity,
    rule_description
FROM rules
ORDER BY
    CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
    affected_rate DESC
