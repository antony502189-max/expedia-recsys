# Stage 2 Dashboard Specification

The Stage 2 dashboard uses only the canonical BI exports under
`data/bi/20260807T121247Z/`. It covers 25 fixed visuals across five pages.

| Page | Visuals | BI mart(s) |
| --- | --- | --- |
| 1. Product Overview | 1-6 | `bi_overview_monthly` |
| 2. Segments & Travel Behaviour | 7-12 | `bi_segments_monthly`, `bi_booking_window`, `bi_traveller_planning_monthly`, `bi_checkin_seasonality` |
| 3. Destinations & Opportunities | 13-18 | `bi_destination_performance`, `bi_hotel_market_performance`, `bi_destination_monthly`, `bi_routes` |
| 4. Observed User Recurrence | 19-21 | `bi_observed_recurrence` |
| 5. Data Quality & Methodology | 22-25 | `bi_acceptance_status`, `bi_missingness_daily`, `bi_proxy_ambiguity`, `bi_booking_population_drift_summary` |

For filtered BI views calculate `booking_interaction_share` as
`SUM(booking_rows) / SUM(interaction_rows)`. Never sum `active_users` over
months. `event_month`, `checkin_month`, `cohort_month`, and `activity_month`
remain intentionally separate time concepts.
