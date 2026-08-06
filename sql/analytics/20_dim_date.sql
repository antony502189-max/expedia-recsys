WITH bounds AS (
    SELECT MIN(event_date) AS min_date, MAX(event_date) AS max_date
    FROM analytics.fct_search_contexts
)
SELECT
    CAST(day_value AS DATE) AS date_day,
    EXTRACT(year FROM day_value)::SMALLINT AS calendar_year,
    EXTRACT(quarter FROM day_value)::TINYINT AS calendar_quarter,
    EXTRACT(month FROM day_value)::TINYINT AS calendar_month,
    STRFTIME(day_value, '%Y-%m') AS year_month,
    EXTRACT(week FROM day_value)::TINYINT AS iso_week,
    EXTRACT(isodow FROM day_value)::TINYINT AS iso_day_of_week,
    STRFTIME(day_value, '%A') AS day_name,
    STRFTIME(day_value, '%B') AS month_name,
    EXTRACT(isodow FROM day_value) IN (6, 7) AS is_weekend,
    CAST(DATE_TRUNC('week', day_value) AS DATE) AS week_start,
    CAST(DATE_TRUNC('month', day_value) AS DATE) AS month_start,
    CAST(DATE_TRUNC('quarter', day_value) AS DATE) AS quarter_start,
    CAST(DATE_TRUNC('year', day_value) AS DATE) AS year_start
FROM bounds
CROSS JOIN GENERATE_SERIES(min_date, max_date, INTERVAL 1 DAY) AS dates(day_value)
