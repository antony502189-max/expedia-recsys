# Canonical Field Dictionary

| Canonical field | Display / type | Meaning, aggregation, source variants, warnings |
| --- | --- | --- |
| `interaction_rows`, `booking_rows` | Interactions, bookings / BIGINT | Additive components. `logged_interaction_rows` is renamed to interactions; these are not searches. |
| `booking_interaction_share` | Booking interaction share / DOUBLE | `SUM(booking_rows)/SUM(interaction_rows)`; never average or confuse with user/recurrence share. |
| `booking_interaction_share_ci_low`, `_high` | Outcome CI / DOUBLE | Non-additive descriptive confidence bounds. |
| `active_users`, `entity_users` | Monthly active, entity users / BIGINT | Different concepts; never sum monthly actives or substitute entity users. |
| `event_date`, `event_month` | Event time / DATE | Observed interaction time, distinct from check-in/cohort fields. |
| `checkin_month`, `cohort_month`, `activity_month`, `observed_age_month` | Planning/recurrence time / DATE, INTEGER | Separate semantic axes; do not rename or merge. |
| `segment_type`, `segment_value`, `segment_sort_order` | Segment dimensions / VARCHAR, INTEGER | Canonical family, value, and display order; families repeat the population. |
| `lead_time_segment`, `stay_segment`, `traveller_segment` and sort fields | Planning segments / VARCHAR, INTEGER | Contract buckets and ordering; do not invent buckets. |
| `destination_id`, `hotel_market`, `origin_id` | Entities / INTEGER, VARCHAR | Distinct entities; do not use the many-to-many bridge for additive joins. |
| `support_level` | Support category / VARCHAR | low <100; adequate <1000; strong >=1000 interactions. |
| `investigation_class`, `investigation_candidate` | Opportunity diagnostics / VARCHAR, BOOLEAN | CI and strong-volume comparison; candidate does not prove a defect. |
| `cohort_users`, `observed_active_users`, `booking_users`, `observed_recurrence_share`, `is_censored` | Recurrence / BIGINT, DOUBLE, BOOLEAN | Observed activity only; censored measures stay NULL. |
| `eligible_rows`, `missing_rows`, `missing_share` | Missingness / BIGINT, DOUBLE | Aggregate components within one field; do not average daily shares. |
| `affected_contexts`, `proxy_contexts`, `affected_share` | Proxy ambiguity / BIGINT, DOUBLE | Ratio by overlapping ambiguity type. |
| `total_variation_distance`, `population_stability_index`, `category_count` | Drift / DOUBLE, BIGINT | Non-additive booking-population drift summary. |
