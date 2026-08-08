SELECT
    user_id,
    MIN(event_date) AS first_event_date,
    CAST(DATE_TRUNC('month', MIN(event_date)) AS DATE) AS first_event_month,
    MAX(event_date) AS last_event_date
FROM analytics.fct_search_contexts
WHERE user_id IS NOT NULL
GROUP BY user_id
