# Third red-team audit: binary acceptance contract

## Current verdict

**NO.** The current artifact is not yet a defensible 10/10 implementation.

This verdict is not based on a desire to add more tables. It follows from several unresolved semantic and engineering blockers. The project may be called maximum-quality only after every blocking item below is implemented and verified on the complete local data.

## The most important semantic boundary

The competition data contains logged customer interactions marked as click or booking. It does not contain every search, every result impression, every session, every checkout step, or every zero-interaction visit.

Therefore the following metric cannot be reconstructed:

```text
search-to-booking conversion
```

The project may publish only clearly named descriptive outcomes such as:

- booking-row share among logged interaction rows;
- cnt-weighted booking-event share among valid similar-event counts;
- booking-bearing share among identified-user proxy interaction contexts;
- share of observed active users with at least one booking row.

None of these is checkout conversion, purchase conversion, or an Expedia-wide KPI.

## Third-audit blockers

### 1. Reconciliation currently proves row-count arithmetic, not content equality

The current raw-to-Parquet reconciliation can pass when row counts match even if accepted values were corrupted, truncated, reordered incorrectly, or parsed differently.

Required:

- compare raw accepted rows and prepared rows as multisets of canonical row fingerprints with multiplicities;
- reconcile each rejected row to exactly one documented quarantine reason or a deterministic primary reason plus all reason flags;
- verify parsed values, not only the number of rows;
- publish accepted, quarantined and total counts with `raw = accepted + quarantine`.

### 2. Duplicate profiling uses a non-cryptographic hash without collision verification

Grouping only by DuckDB `HASH(...)` can merge different rows after a collision and is not an enduring cross-version data contract.

Required:

- canonical field serialization with explicit null/type handling;
- SHA-256 content fingerprint or exact all-column grouping;
- multiplicity-aware duplicate groups;
- collision verification for any shortened technical hash;
- separate exact duplicates from legitimate repeated events represented by `cnt`.

### 3. The profile is currently calculated on recommendation-prepared Parquet

Rows rejected by the recommendation preparation are absent from the main distribution profile.

Required:

- analytics-specific raw-string landing layer;
- typed accepted staging;
- quarantine table preserving raw values and parse/validation reasons;
- separate profiles for raw, accepted and quarantine populations;
- comparison showing whether exclusions change booking share or important segment distributions.

### 4. No-search and no-interaction populations are absent

An `is_booking = 0` row is documented as a click, not a search that failed to book. Searches with no logged click or booking are not represented.

Required:

- prohibit the words `search conversion`, `funnel conversion`, and `checkout conversion` in metric contracts;
- use `logged_interaction` and `proxy_interaction_context` terminology;
- explain the selected denominator beside every rate;
- include denominator coverage and anonymous-user coverage in every relevant mart.

### 5. The source is a random competition selection and is explicitly not representative of Expedia-wide statistics

Unknown sampling probabilities mean no post-stratification or population estimate can be justified.

Required:

- frame every result as descriptive of the supplied historical sample;
- never label dashboard values as current Expedia product health;
- preserve sample size and coverage beside every metric;
- prevent extrapolation to users, revenue or total traffic outside the sample.

### 6. User lifecycle and retention terminology is still too strong

First observation is not acquisition or registration. Absence in a later month is not necessarily churn. The observation window is left- and right-censored.

Required:

- rename lifecycle fields to `first_observed_*`, `previously_observed`, and `observed_recurrence_rate`;
- do not publish a generic `retention_rate` unless the denominator and observability assumptions are explicit;
- include cohort size, observable horizon and right-censoring flags;
- separate identified-user coverage from all interaction rows.

### 7. Destination is not functionally dependent on one hotel market or country

Selecting a modal/primary hotel market for a destination hides a many-to-many relationship and can create false geography.

Required:

- keep destination latent features in `dim_destination`;
- create a destination-to-hotel-market bridge with interaction and booking numerators/denominators;
- expose market concentration and ambiguity;
- avoid treating modal geography as a stable destination attribute.

### 8. Origin geography requires composite keys

City and region identifiers must not be assumed globally unique outside their documented hierarchy.

Required:

- define origin grain as country × region × city;
- create a deterministic composite origin key;
- use that key in route marts;
- retain unknown components rather than collapsing them into another geography.

### 9. Train and test support different analytical populations

Train contains click and booking rows from 2013–2014; test contains only booking events from 2015.

Required:

- never append test to train for outcome KPIs;
- compare test only with the booking subset of train when studying temporal covariate drift;
- label that analysis `booking-event population drift`, not product-traffic drift;
- report unseen categories and destination-feature coverage separately.

### 10. Missingness must be treated as a possible logging process

Overall null rates cannot distinguish user behavior from changes in instrumentation.

Required:

- null/invalid rates by month, site, channel, device, package and major anonymized geography;
- structural-break or material-drift flags;
- coverage denominators in downstream marts;
- sensitivity views with and without records missing required analytical fields.

### 11. Rate comparison needs uncertainty and composition controls

Raw rates for sparse destinations and segments are unstable. Large sample sizes also make p-values uninformative.

Required:

- numerator, denominator and rate in every rate mart;
- Wilson interval or another documented binomial interval where applicable;
- minimum support based on interval width/effective sample, not an arbitrary row threshold alone;
- effect sizes and absolute percentage-point differences;
- stratified or mix-adjusted sensitivity for major confounders;
- no causal language without an experiment.

### 12. Context aggregation still contains non-deterministic or lossy choices

`ANY_VALUE`, tie-prone `MODE`, arbitrary distance segments and one booked cluster can conceal multi-valued contexts.

Required:

- prove constancy before selecting a context-level value;
- otherwise publish min/median/max, distribution counts or ambiguity flags;
- deterministic tie-breaking for modes;
- preserve multiple booking clusters/markets when observed;
- retain hotel-specific distance only at interaction grain and publish context distance summaries.

### 13. Output reproducibility is not complete

Atomic DuckDB replacement alone is insufficient. Current Parquet exports can form a mixed build after failure, and multithreaded unordered output is not byte-deterministic.

Required:

- immutable `build_id` directories for database, Parquet and reports;
- publish `LATEST_BUILD.json` only after all gates pass;
- preserve the previous successful build;
- record Git commit, dirty state, uv.lock hash, Python version, DuckDB version, OS, configuration and source hashes;
- logical order-independent content checksums for every object;
- schema contract and semantic version for every published table.

### 14. BI physical design is incomplete

One large fact Parquet is valid storage but not the strongest delivery format for interactive BI.

Required:

- partition large facts by event year/month;
- preserve compact aggregate marts as single files;
- provide stable sort columns and segment-order dimension;
- publish relationships, primary grain, additive/semi-additive measures and aggregation rules;
- include example BI-safe queries that recompute rates from numerators and denominators.

### 15. End-to-end tests are still missing

Specification tests do not validate SQL semantics.

Required synthetic cases:

- exact duplicate rows;
- valid repeated events with `cnt > 1`;
- malformed timestamps and numeric fields;
- invalid booking domains;
- missing and nonpositive `cnt`;
- anonymous users;
- multiple clusters/markets and multiple bookings in one proxy context;
- destination-to-market many-to-many relationships;
- invalid stay and lead-time dates;
- train/test unseen categories;
- cohort censoring.

Every SQL object must execute on this fixture and pass grain, reconciliation, rate and schema assertions.

## Closed target architecture

The final first project artifact should contain the following logical layers. New tables are allowed only when a real dashboard question or quality contract requires them.

### Landing and staging

- `raw_train_strings`
- `raw_test_strings`
- `raw_destinations_strings`
- `stg_train_accepted`
- `stg_train_quarantine`
- `stg_test_accepted`
- `stg_test_quarantine`
- `stg_destinations_accepted`
- `stg_destinations_quarantine`

### Core analytical facts

- `fct_hotel_interactions`
- `fct_identified_proxy_interaction_contexts`
- `fct_user_day`

### Dimensions and bridges

- `dim_date`
- `dim_destination`
- `dim_user_first_observed`
- `dim_segment_definition`
- `dim_origin_location`
- `bridge_destination_hotel_market`

### Published marts

- sample activity daily/monthly;
- logged interaction outcomes daily/monthly;
- identified proxy-context outcomes daily/monthly;
- user-day outcomes daily/monthly;
- segment daily/monthly;
- site/channel/device/package performance;
- destination, market and route performance;
- booking-window, stay, party and check-in seasonality;
- user observed-activity profile;
- observed cohort recurrence;
- hotel-cluster descriptive performance;
- train-to-test booking-population drift;
- source profile, quarantine, missingness drift and DQ marts.

## Binary 10/10 acceptance matrix

The answer may become **YES** only when all rows below are PASS.

| Gate | Required evidence |
|---|---|
| Source completeness | Raw = accepted + quarantine for every source |
| Content equivalence | Accepted raw multiset equals typed staging/processed multiset |
| Semantic contract | No prohibited conversion/retention/population claims |
| Determinism | Two clean full builds produce identical logical checksums |
| Grain integrity | Every published grain key is unique |
| Reconciliation | Facts, daily, monthly and every segment family reconcile |
| Statistical safety | Numerators, denominators, intervals and support are present |
| Censoring/coverage | User and proxy metrics expose coverage and observation limits |
| Many-to-many safety | Destination/market and origin hierarchies are modeled correctly |
| Data quality | Quarantine, missingness drift and ambiguity are published |
| Physical delivery | Immutable versioned DB/Parquet build with rollback pointer |
| BI contract | Schemas, relationships, aggregation rules and safe queries documented |
| Tests | Full synthetic end-to-end suite passes |
| Full-data execution | Complete local build succeeds on all source rows |
| Manual verification | Representative records and headline totals are independently checked |

## Final rule

No further speculative audit cycle is needed after this document. The remaining uncertainty is empirical, not conceptual: actual source distributions, full-run behavior and test results.

The implementation is **10/10 only after the closed acceptance matrix passes**. Until then the honest answer is **NO**.
