WITH user_month AS (
    SELECT
        c.user_id,
        u.first_event_month AS cohort_month,
        c.event_month AS activity_month,
        DATE_DIFF('month', u.first_event_month, c.event_month)::INTEGER AS cohort_age_month,
        COUNT(*)::BIGINT AS search_contexts,
        COUNT(*) FILTER (WHERE c.has_booking)::BIGINT AS booking_contexts
    FROM analytics.fct_search_contexts c
    JOIN analytics.dim_user_first_seen u USING (user_id)
    GROUP BY c.user_id, u.first_event_month, c.event_month
)
SELECT
    cohort_month,
    activity_month,
    cohort_age_month,
    COUNT(DISTINCT user_id)::BIGINT AS active_users,
    SUM(search_contexts)::BIGINT AS search_contexts,
    SUM(booking_contexts)::BIGINT AS booking_contexts,
    SUM(booking_contexts)::DOUBLE / NULLIF(SUM(search_contexts), 0) AS booking_context_rate
FROM user_month
GROUP BY cohort_month, activity_month, cohort_age_month
ORDER BY cohort_month, activity_month
