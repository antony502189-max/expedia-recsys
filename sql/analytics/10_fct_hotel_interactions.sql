WITH source AS (
    SELECT
        ROW_NUMBER() OVER () AS source_row_id,
        date_time AS event_datetime,
        CAST(date_time AS DATE) AS event_date,
        CAST(DATE_TRUNC('month', date_time) AS DATE) AS event_month,
        CAST(DATE_TRUNC('week', date_time) AS DATE) AS event_week,
        EXTRACT(isodow FROM date_time)::TINYINT AS event_iso_day_of_week,
        EXTRACT(hour FROM date_time)::TINYINT AS event_hour,
        site_name,
        posa_continent,
        user_location_country,
        user_location_region,
        user_location_city,
        orig_destination_distance_key,
        orig_destination_distance,
        user_id,
        is_mobile,
        is_package,
        channel,
        srch_ci AS checkin_date,
        srch_co AS checkout_date,
        DATE_DIFF('day', CAST(date_time AS DATE), srch_ci)::INTEGER AS lead_time_days,
        DATE_DIFF('day', srch_ci, srch_co)::INTEGER AS stay_nights,
        srch_adults_cnt,
        srch_children_cnt,
        srch_rm_cnt,
        COALESCE(srch_adults_cnt, 0) + COALESCE(srch_children_cnt, 0) AS party_size,
        srch_destination_id,
        srch_destination_type_id,
        is_booking,
        cnt AS source_cnt,
        GREATEST(COALESCE(cnt, 1), 1)::BIGINT AS event_weight,
        hotel_continent,
        hotel_country,
        hotel_market,
        hotel_cluster
    FROM raw.train_events
), enriched AS (
    SELECT
        *,
        CASE WHEN is_booking = 1 THEN 'booking' ELSE 'click' END AS interaction_type,
        CASE
            WHEN is_mobile = 1 THEN 'mobile'
            WHEN is_mobile = 0 THEN 'desktop'
            ELSE 'unknown'
        END AS device_segment,
        CASE
            WHEN is_package = 1 THEN 'package'
            WHEN is_package = 0 THEN 'standalone'
            ELSE 'unknown'
        END AS package_segment,
        CASE
            WHEN srch_children_cnt > 0 THEN 'family'
            WHEN srch_adults_cnt = 1 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'solo'
            WHEN srch_adults_cnt = 2 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'couple'
            WHEN srch_adults_cnt >= 3 AND COALESCE(srch_children_cnt, 0) = 0 THEN 'group'
            ELSE 'unknown'
        END AS traveller_segment,
        CASE
            WHEN lead_time_days IS NULL THEN 'missing'
            WHEN lead_time_days < 0 THEN 'invalid_negative'
            WHEN lead_time_days = 0 THEN 'same_day'
            WHEN lead_time_days <= 7 THEN '01_07_days'
            WHEN lead_time_days <= 30 THEN '08_30_days'
            WHEN lead_time_days <= 90 THEN '31_90_days'
            WHEN lead_time_days <= 180 THEN '91_180_days'
            ELSE '181_plus_days'
        END AS lead_time_segment,
        CASE
            WHEN stay_nights IS NULL THEN 'missing'
            WHEN stay_nights <= 0 THEN 'invalid_nonpositive'
            WHEN stay_nights = 1 THEN '01_night'
            WHEN stay_nights <= 3 THEN '02_03_nights'
            WHEN stay_nights <= 7 THEN '04_07_nights'
            WHEN stay_nights <= 14 THEN '08_14_nights'
            ELSE '15_plus_nights'
        END AS stay_segment,
        CASE
            WHEN orig_destination_distance IS NULL THEN 'missing'
            WHEN orig_destination_distance < 250 THEN '0000_0249'
            WHEN orig_destination_distance < 750 THEN '0250_0749'
            WHEN orig_destination_distance < 1500 THEN '0750_1499'
            WHEN orig_destination_distance < 3000 THEN '1500_2999'
            ELSE '3000_plus'
        END AS distance_segment,
        checkin_date IS NOT NULL
            AND checkout_date IS NOT NULL
            AND checkout_date > checkin_date AS has_valid_stay_dates,
        checkin_date IS NOT NULL
            AND checkin_date >= event_date AS has_valid_lead_time,
        MD5(CONCAT_WS('|',
            COALESCE(CAST(user_id AS VARCHAR), '<NULL>'),
            COALESCE(CAST(event_datetime AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_destination_id AS VARCHAR), '<NULL>'),
            COALESCE(CAST(hotel_cluster AS VARCHAR), '<NULL>'),
            COALESCE(CAST(is_booking AS VARCHAR), '<NULL>'),
            COALESCE(CAST(source_row_id AS VARCHAR), '<NULL>')
        )) AS interaction_key,
        MD5(CONCAT_WS('|',
            COALESCE(CAST(user_id AS VARCHAR), '<NULL>'),
            COALESCE(CAST(event_datetime AS VARCHAR), '<NULL>'),
            COALESCE(CAST(site_name AS VARCHAR), '<NULL>'),
            COALESCE(CAST(user_location_country AS VARCHAR), '<NULL>'),
            COALESCE(CAST(user_location_region AS VARCHAR), '<NULL>'),
            COALESCE(CAST(user_location_city AS VARCHAR), '<NULL>'),
            COALESCE(CAST(is_mobile AS VARCHAR), '<NULL>'),
            COALESCE(CAST(is_package AS VARCHAR), '<NULL>'),
            COALESCE(CAST(channel AS VARCHAR), '<NULL>'),
            COALESCE(CAST(checkin_date AS VARCHAR), '<NULL>'),
            COALESCE(CAST(checkout_date AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_adults_cnt AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_children_cnt AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_rm_cnt AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_destination_id AS VARCHAR), '<NULL>'),
            COALESCE(CAST(srch_destination_type_id AS VARCHAR), '<NULL>')
        )) AS search_context_key
    FROM source
)
SELECT * FROM enriched
