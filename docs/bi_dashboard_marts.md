# Canonical Dashboard BI Marts

All marts are Parquet exports in `data/bi/20260807T121247Z/`. Ratios retain
additive components. The primary outcome is always
`SUM(booking_rows) / SUM(interaction_rows)`.

| BI mart | Purpose, page, visuals | Sources | Grain | Safe aggregation, filters, NULLs, caveats |
| --- | --- | --- | --- | --- |
| `bi_overview_monthly` | Overview, P1 V1-6 | activity, outcome, proxy monthly | event month | January 2013 is partial; `active_users` is monthly distinct. |
| `bi_segments_monthly` | Segments, P2 V7-9 | segment monthly, definitions | month x type x value | Filter one `segment_type`; families repeat population. |
| `bi_booking_window` | Heatmap, P2 V10 | booking window, definitions | lead x stay | All 30 contract cells; use supplied sort fields. |
| `bi_traveller_planning_monthly` | Planning, P2 V11 | travel patterns, definitions | month x traveller | Valid lead/stay averages are interaction-weighted; invalid values excluded. |
| `bi_checkin_seasonality` | Seasonality, P2 V12 | check-in seasonality | check-in month x traveller | `checkin_month` is not `event_month`; future check-ins are expected. |
| `bi_destination_performance` | Destinations, P3 V13-15 | destination performance | destination | Defaults to strong support; candidate flags are investigation leads, not defects. |
| `bi_hotel_market_performance` | Markets, P3 V16 | market performance | hotel market | Never make additive joins through the destination-market bridge. |
| `bi_destination_monthly` | Destination trend, P3 V17 | destination monthly | month x destination | Low-support cells are labelled; `entity_users` is not active users. |
| `bi_routes` | Routes, P3 V18 | origin-destination routes | origin x destination | Full extract; visual may filter to strong support. |
| `bi_observed_recurrence` | Recurrence, P4 V19-21 | observed recurrence | cohort x activity month | Count cohorts at age 0 once; censored cells remain NULL; not retention. |
| `bi_acceptance_status` | Acceptance, P5 V22 | acceptance artifact | one row | 43/43 exact reproducibility status. |
| `bi_missingness_daily` | Missingness, P5 V23 | missingness daily | date x field | Aggregate numerator and denominator within a field. |
| `bi_proxy_ambiguity` | Proxy quality, P5 V24 | proxy ambiguity | ambiguity type | Ambiguity types overlap; never sum affected contexts across types. |
| `bi_booking_population_drift_summary` | Drift, P5 V25 | population drift | dimension | Train-to-test booking population; measures are non-additive. |
