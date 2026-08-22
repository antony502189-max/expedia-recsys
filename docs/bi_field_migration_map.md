# BI Field Migration Map

| Source mart | Source field | BI mart | Canonical field | Action |
| --- | --- | --- | --- | --- |
| `dm_sample_activity_monthly` | `logged_interaction_rows` | `bi_overview_monthly` | `interaction_rows` | Rename. |
| `dm_sample_activity_monthly` | `identified_active_users` | `bi_overview_monthly` | `active_users` | Rename; monthly distinct. |
| `dm_proxy_context_monthly` | `proxy_search_contexts` | `bi_overview_monthly` | `proxy_contexts` | Rename. |
| outcome/window/entity marts | `booking_interaction_share` | outcome BI marts | `booking_interaction_share` | Retain with components. |
| `dm_segment_monthly` | segment fields | `bi_segments_monthly` | segment fields | Add sort order; derive support. |
| `dm_travel_patterns` | `avg_valid_lead_time_days` | `bi_traveller_planning_monthly` | `avg_valid_lead_days` | Interaction-weighted aggregate. |
| `dm_destination_*` | `srch_destination_id` | destination BI marts | `destination_id` | Rename. |
| entity/route marts | `identified_users` | entity/route BI marts | `entity_users` | Rename; not active users. |
| `dm_observed_recurrence` | `first_observed_month` | recurrence BI mart | `cohort_month` | Rename. |
| `dm_observed_recurrence` | `observed_booking_users` | recurrence BI mart | `booking_users` | Rename. |
| `dm_observed_recurrence` | `is_right_censored` | recurrence BI mart | `is_censored` | Rename; preserve NULLs. |
| drift summary | `compared_categories` | drift BI mart | `category_count` | Rename. |
