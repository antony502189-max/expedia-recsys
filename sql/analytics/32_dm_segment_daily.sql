WITH contextual AS (
    SELECT
        c.*,
        CASE WHEN c.event_date = u.first_event_date THEN 'new' ELSE 'returning' END AS lifecycle_segment
    FROM analytics.fct_search_contexts c
    LEFT JOIN analytics.dim_user_first_seen u USING (user_id)
), segmented AS (
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'device' AS segment_type, device_segment AS segment_value FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'package', package_segment FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'traveller', traveller_segment FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'lead_time', lead_time_segment FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'stay', stay_segment FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'distance', distance_segment FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'channel', COALESCE(CAST(channel AS VARCHAR), 'unknown') FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'site', COALESCE(CAST(site_name AS VARCHAR), 'unknown') FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'destination_type', COALESCE(CAST(srch_destination_type_id AS VARCHAR), 'unknown') FROM contextual
    UNION ALL
    SELECT event_date, user_id, has_booking, interaction_rows, weighted_interactions,
           'user_lifecycle', lifecycle_segment FROM contextual
)
SELECT
    event_date,
    segment_type,
    segment_value,
    COUNT(*)::BIGINT AS search_contexts,
    COUNT(*) FILTER (WHERE has_booking)::BIGINT AS booking_contexts,
    COUNT(*) FILTER (WHERE has_booking)::DOUBLE / NULLIF(COUNT(*), 0) AS booking_context_rate,
    COUNT(DISTINCT user_id)::BIGINT AS active_users,
    SUM(interaction_rows)::BIGINT AS interaction_rows,
    SUM(weighted_interactions)::BIGINT AS weighted_interactions,
    COUNT(*) >= 100 AS is_stable_sample
FROM segmented
GROUP BY event_date, segment_type, segment_value
ORDER BY event_date, segment_type, segment_value
