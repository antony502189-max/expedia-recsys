# Stage 2 Dashboard Mart Mapping

| Visual IDs | Canonical BI source | Accepted Stage 1 lineage |
| --- | --- | --- |
| 1-6 | `bi_overview_monthly` | `dm_sample_activity_monthly`, `dm_interaction_outcome_monthly`, `dm_proxy_context_monthly` |
| 7-9 | `bi_segments_monthly` | `dm_segment_monthly`, `dim_segment_definition` |
| 10 | `bi_booking_window` | `dm_booking_window`, `dim_segment_definition` |
| 11 | `bi_traveller_planning_monthly` | `dm_travel_patterns`, `dim_segment_definition` |
| 12 | `bi_checkin_seasonality` | `dm_checkin_seasonality` |
| 13-15 | `bi_destination_performance` | `dm_destination_performance` |
| 16 | `bi_hotel_market_performance` | `dm_hotel_market_performance` |
| 17 | `bi_destination_monthly` | `dm_destination_monthly` |
| 18 | `bi_routes` | `dm_origin_destination_routes` |
| 19-21 | `bi_observed_recurrence` | `dm_observed_recurrence` |
| 22 | `bi_acceptance_status` | accepted Stage 1 acceptance artifact |
| 23 | `bi_missingness_daily` | `dm_missingness_daily` |
| 24 | `bi_proxy_ambiguity` | `dm_proxy_context_ambiguity` |
| 25 | `bi_booking_population_drift_summary` | `dm_booking_population_drift_summary` |

`bi_routes` retains all 3,810,666 route rows. DataLens can filter it to
`support_level = 'strong'`; no lossy pre-truncation is published.
