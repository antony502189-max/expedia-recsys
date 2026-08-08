WITH observed AS (
    SELECT
        srch_destination_id,
        MODE(srch_destination_type_id) AS destination_type_id,
        MODE(primary_hotel_continent) AS primary_hotel_continent,
        MODE(primary_hotel_country) AS primary_hotel_country,
        MODE(primary_hotel_market) AS primary_hotel_market,
        MIN(event_date) AS first_seen_date,
        MAX(event_date) AS last_seen_date,
        COUNT(*)::BIGINT AS observed_search_contexts,
        COUNT(*) FILTER (WHERE has_booking)::BIGINT AS observed_booking_contexts
    FROM analytics.fct_search_contexts
    WHERE srch_destination_id IS NOT NULL
    GROUP BY srch_destination_id
)
SELECT
    d.*,
    o.destination_type_id,
    o.primary_hotel_continent,
    o.primary_hotel_country,
    o.primary_hotel_market,
    o.first_seen_date,
    o.last_seen_date,
    COALESCE(o.observed_search_contexts, 0) AS observed_search_contexts,
    COALESCE(o.observed_booking_contexts, 0) AS observed_booking_contexts
FROM raw.destinations d
LEFT JOIN observed o USING (srch_destination_id)
