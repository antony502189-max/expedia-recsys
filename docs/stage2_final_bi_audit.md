# Stage 2 Final BI Audit

## Executive verdict

**READY FOR DATALENS.** The final audit passed for accepted Stage 1 build
`20260807T121247Z` and BI contract `1.0.0`.

## Datasets audited

All 14 manifest-listed Parquet datasets were opened and checked for readability,
checksum, expected schema, documented grain, unique keys, and the absence of
temporary or duplicate files.

## Canonical naming and grains

The audit found one real issue: secondary approved segment families `channel`
and `site` were labelled invalid and had no sort order. The BI builder now uses
their numeric IDs as stable sort order and marks them valid. A regression test
ensures that this cannot return. No Stage 1 schema, mart, or file changed.

Canonical outcome names are consistent (`interaction_rows`, `booking_rows`,
`booking_interaction_share`); legacy Stage 1 names are absent from the BI
exports. Event, check-in, cohort, and activity time axes remain separate.

## KPI reconciliation and time semantics

- 37,670,293 interactions; 3,000,693 bookings; 7.9656747% booking interaction share.
- December 2014 active users: 353,387.
- Event period: 2013-01 through 2014-12; January 2013 is partial.
- Check-in period correctly reaches 2016-11.

## Segments, travel, destinations, and markets

All seven approved segment families are present. The booking-window matrix has
30 cells with both regression anchors matching. There are 2,970 strong
destinations and 1,526 strong hotel markets. Destination and market marts
independently reconcile to the global totals; no bridge-based double counting
is present. Investigation candidates are correctly documented as candidates,
not product defects.

## Recurrence and data quality

Recurrence has 576 cells, 276 censored cells with NULL observed measures, and
1,198,786 age-zero cohort users. Age-one and age-three weighted observed
recurrence match 30.6724% and 23.0019%. Distance missingness and proxy
ambiguity anchors match their approved values; ambiguity types remain
overlapping.

## Visual coverage and caveats

All 5 pages and 25 visuals use only BI marts; see
`artifacts/dashboard/visual_coverage_registry.md`. Ratios must always be
calculated from additive numerator/denominator fields. Do not average shares,
sum active users across months, treat observed recurrence as retention, or
combine segment families or destination/market entities additively.

## Final verdict

**READY FOR DATALENS.**
