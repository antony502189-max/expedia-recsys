# Stage 2 KPI Dictionary

| KPI | Canonical formula | BI aggregation and warning |
| --- | --- | --- |
| Logged interactions | `interaction_rows` | `SUM(interaction_rows)`; logged interactions, not searches or sessions. |
| Booking rows | `booking_rows` | `SUM(booking_rows)`. |
| Booking interaction share | `booking_rows / interaction_rows` | `SUM(booking_rows) / SUM(interaction_rows)`; never `AVG`; not CVR. |
| Active users | `active_users` | Monthly distinct; do not sum over months. |
| Observed recurrence | `observed_active_users / cohort_users` | Cohort-weighted; observed activity, not retention; censored values are NULL. |
| Missing share | `missing_rows / eligible_rows` | Aggregate components within each field; never average daily percentages. |
| Proxy affected share | `affected_contexts / proxy_contexts` | Per ambiguity type; types overlap and cannot be summed. |
| Population drift | TVD / PSI | Non-additive train-booking versus test-booking population measures. |
