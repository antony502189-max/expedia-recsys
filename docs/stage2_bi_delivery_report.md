# Stage 2 BI Delivery Report

Source build: `20260807T121247Z`
Canonical contract: `1.0.0`
Status: **READY FOR DATALENS**

## Delivery

Fourteen dashboard-specific marts were exported under
`data/bi/20260807T121247Z/`: overview (24 rows), segments (1,738), booking
window (30), traveller planning (120), check-in seasonality (201), destination
performance (59,455), hotel-market performance (2,118), destination monthly
(462,317), routes (3,810,666), observed recurrence (576), acceptance status
(1), missingness (5,068), proxy ambiguity (4), and population drift summary
(6). The manifest records source lineage, columns, grain, row count, contract
version, build ID, and SHA-256 checksum for every export.

## Reconciliation and validation

- Overall interactions: 37,670,293; bookings: 3,000,693; share: 7.9656747%.
- December 2014 active users: 353,387.
- Strong destinations: 2,970; strong markets: 1,526.
- Recurrence age-zero cohort users: 1,198,786; 276 censored cells are NULL.
- BI validation passed source reconciliation, canonical columns/types, grain,
  bounds, support thresholds, anchors, manifest checksum, and Stage 1
  acceptance (43/43 exact objects).

All five pages and 25/25 visuals map directly to BI marts. No dashboard visual
uses a Stage 1 mart directly. Stage 1 schemas and Parquet data were not
modified. Important caveats are preserved in the canonical dictionary: ratios
use additive numerator/denominator components, segment families are not
additive across types, destination and hotel-market entities are distinct, and
observed recurrence is not retention.
