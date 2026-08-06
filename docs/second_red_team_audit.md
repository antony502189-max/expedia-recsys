# Second red-team audit: what the first design still missed

## 1. The recommendation preparation layer is not an analytical raw layer

The existing `prepare_data` query filters rows with an unparseable `date_time` or a
`hotel_cluster` outside 0–99. It also filters destinations with an invalid destination ID.
That behavior is acceptable for a recommendation baseline, but an analytical data product
must not claim complete source preservation without reconciling the rejected population.

Required design:

- reconcile raw CSV row counts with prepared Parquet row counts;
- report every parse failure by column;
- create an analytics-specific all-row staging layer;
- keep malformed rows in a quarantine table with rejection reasons;
- build product facts only from explicitly eligible rows while retaining the denominator of
  excluded rows in data-quality reporting.

## 2. Source profiling must precede segment design

The current lead-time, stay and distance bands were selected before calculating full-data
quantiles and anomalous ranges. This is backwards.

Required sequence:

1. source schema and row reconciliation;
2. null, cardinality and distribution profile;
3. empirical quantiles and business-readable cut points;
4. segment definitions with fixed sort order and version;
5. facts and marts.

No segment boundary is final until the full profile is reviewed.

## 3. Competition data is not audited product telemetry

The supplied data is a historical competition sample designed for hotel-cluster prediction.
It does not prove complete coverage of Expedia traffic, users, markets or sessions.

Consequences:

- row counts must be described as dataset interactions, not Expedia traffic;
- trends may reflect sampling or logging composition changes;
- booking shares are descriptive sample statistics, not official business conversion;
- findings cannot be generalized to the current product without fresh telemetry.

## 4. The processed train and test sets must not be mixed in outcome KPIs

The test set has a later period and no booking label or hotel cluster. It can be profiled for
covariate drift, but it cannot be appended to the labelled train period and treated as missing
bookings.

Required outputs:

- labelled-train product marts;
- separate train-vs-test feature-drift report;
- no combined booking-rate denominator.

## 5. Anonymous users cannot be safely sessionized

Rows with null `user_id` can collide when a proxy context is built only from timestamp,
location and trip parameters. Treating those rows as one user request can create false
sessions.

Required rule:

- strict proxy contexts are calculated only for identified users;
- anonymous activity remains available in interaction-level metrics;
- identified-user coverage is always shown beside proxy-context metrics.

## 6. Geographic codes are anonymized identifiers, not display-ready geography

`user_location_country`, `hotel_country`, regions, cities, markets and destinations are numeric
codes without a provided lookup to human-readable names or coordinates.

Consequences:

- no world map or named-country conclusion without a verified mapping;
- charts must label them as anonymized IDs;
- latent destination features `d1`–`d149` cannot be interpreted as business attributes.

## 7. Event time zone is unknown

The source timestamp has no documented time-zone field. Hour-of-day and even local weekday
comparisons can be distorted across markets.

Required rule:

- retain source timestamp as timezone-unspecified;
- use date-level trends as the primary temporal analysis;
- publish hourly analysis only as exploratory and stratified by site/market where possible.

## 8. Missingness is likely structured

Distance, user ID and travel-date missingness may vary by site, country, device, channel or
period. A global null rate is insufficient.

Required marts:

- missingness by date;
- missingness by site, channel, device and broad origin segment;
- coverage flags next to every metric that depends on an optional field.

## 9. Calendar edges create censoring

First-observed users at the start of the dataset may be old users, while cohorts near the end
have less time to return. Check-in dates can also extend beyond the event observation window.

Required rules:

- call cohorts `first_observed`, not acquired or registered;
- publish cohort size and right-censoring flags;
- exclude incomplete cohort ages from comparisons;
- flag incomplete first and last event months in time-series marts.

## 10. Segment comparisons can be confounded

A raw mobile-vs-desktop rate can be driven by destination, site, channel, package status or
trip composition. The mart layer must support stratified comparisons and composition analysis.

Required support:

- numerator and denominator by segment;
- segment mix over time;
- stratified cuts by site/channel/destination support tier;
- no causal language from observational differences.

## 11. High-cardinality user data should not be a dashboard source

A user-level profile is useful for offline analysis but is inefficient and unnecessary for the
main BI layer. It also increases governance risk even with anonymized IDs.

Required rule:

- keep user-level facts in the analytical backend;
- export only aggregated lifecycle and activity marts to the dashboard layer;
- never expose raw user IDs in presentation artifacts.

## 12. Build comparison is part of data quality

A build can pass internal reconciliations and still shift materially from the previous build
because of a source replacement, schema change or logic regression.

Required checks:

- previous-vs-current row counts;
- date-range changes;
- booking-share changes;
- null-rate changes;
- category-cardinality changes;
- explicit approval for large unexpected deltas.

## Immediate implementation decision

The existing marts are frozen as a prototype. The first executable phase is now:

```text
raw-to-processed reconciliation
-> full source profile
-> review of actual distributions and rejected rows
-> analytics-specific staging contract
-> corrected facts
-> final marts
```

The branch must not build or publish the prototype marts by default before the source audit has
been reviewed.
