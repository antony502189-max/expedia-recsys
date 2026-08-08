# Third red-team audit — closure report

## Final verdict

**YES. Stage 1 satisfies the closed 10/10 acceptance contract.**

This document was originally written as a blocking pre-acceptance audit. Its purpose is now historical: preserve the list of risks that had to be closed before the processed-data product and analytical marts could be called final.

Accepted full-data builds:

- `20260807T103804Z`;
- `20260807T121247Z`.

Final evidence:

- all full-data quality gates passed;
- raw/staging/quarantine reconciliation passed;
- representative rows, headline totals and quarantine were manually reviewed;
- exact reproducibility audit: **43/43 base-table objects identical**;
- final acceptance: `VERDICT=YES`, `PASSED=True`, `FAILURES=0`.

## Semantic boundary

The competition source contains logged customer interactions marked as click or booking. It does not contain every search, impression, session, checkout step, payment, cancellation or zero-interaction visit.

Therefore Stage 1 does **not** publish search-to-booking conversion or other unsupported Expedia-wide KPIs.

Primary descriptive outcome:

```text
booking_interaction_share = booking_rows / logged_interaction_rows
```

Additional proxy/user metrics are published only with explicit denominator and coverage.

## Closure of original blockers

| Original blocker | Final resolution |
|---|---|
| Row-count-only reconciliation | Canonical fingerprints + multiplicity-aware content multiset reconciliation |
| Non-cryptographic duplicate identity | Length-prefixed SHA-256 raw-row fingerprints |
| Profiling only prepared recommendation data | Dedicated raw string landing, typed accepted staging and quarantine |
| Missing search/no-interaction population | Unsupported funnel/conversion terminology prohibited by contract |
| Non-representative competition sample | Semantic scope explicitly limited to supplied historical sample |
| Overstated lifecycle/retention | `first_observed_*` / `observed_recurrence` terminology + censoring metadata |
| Destination assumed to have one market | Explicit `bridge_destination_hotel_market` many-to-many model |
| Unsafe origin geography keys | Deterministic composite origin dimension |
| Train/test population mismatch | Test isolated from outcome KPIs; only booking-population drift is published |
| Missingness treated as incidental | Dedicated missingness/validity drift marts |
| Sparse rate instability | Additive numerator/denominator + Wilson intervals/support metadata |
| Lossy proxy aggregation | Deterministic proxy semantics and explicit ambiguity diagnostics |
| Mixed/non-versioned outputs | Immutable build directories + atomic `LATEST_BUILD.json` |
| Weak BI physical design | Partitioned large facts + compact BI marts + segment ordering contract |
| Missing end-to-end SQL tests | Synthetic end-to-end fixture executes the final pipeline across thread counts |

## Closed target architecture

### Landing / staging

- raw train/test/destination landing tables;
- `stg_train_accepted` / `quarantine_train`;
- `stg_test_accepted` / `quarantine_test`;
- `stg_destinations_accepted` / `quarantine_destinations`;
- reconciliation metadata.

### Core facts

- `fct_hotel_interactions`;
- `fct_proxy_search_contexts`;
- `fct_user_day`.

### Dimensions / bridge

- `dim_date`;
- `dim_origin`;
- `dim_destination`;
- `dim_segment_definition`;
- `bridge_destination_hotel_market`.

### Published marts

The final layer covers:

- sample activity daily/monthly;
- logged interaction outcomes daily/monthly;
- identified proxy-context outcomes daily/monthly;
- identified user-day outcomes daily/monthly;
- long-format segment daily/monthly;
- destination, hotel-market and route performance;
- booking-window, stay, party and check-in seasonality;
- observed recurrence with right-censoring;
- missingness/validity drift and proxy ambiguity;
- train-vs-test booking-population drift;
- source/staging/semantic data-quality summary.

## 10/10 acceptance matrix — final state

| Gate | Status | Evidence |
|---|---|---|
| Source completeness | PASS | `raw = accepted + quarantine` for train/test/destinations |
| Content equivalence | PASS | canonical multiset reconciliation |
| Semantic contract | PASS | prohibited public terms enforced |
| Determinism | PASS | two full independent builds + exact audit |
| Grain integrity | PASS | unique grain checks for published objects |
| Reconciliation | PASS | facts, daily, monthly, destinations, markets, routes, bridge and segment families |
| Statistical safety | PASS | numerators/denominators, bounded rates, Wilson intervals/support |
| Censoring/coverage | PASS | proxy coverage + right-censored recurrence semantics |
| Many-to-many safety | PASS | destination-market bridge + composite origin |
| Data quality | PASS | quarantine, missingness, ambiguity and drift marts |
| Physical delivery | PASS | immutable versioned DuckDB/Parquet + rollback pointer |
| BI contract | PASS | grains, semantics, segment ordering and aggregation rules documented |
| Tests | PASS | synthetic end-to-end build/reproducibility tests |
| Full-data execution | PASS | complete local source populations processed |
| Manual verification | PASS | representative rows, headline totals and quarantine reviewed |

## Reproducibility note

The accepted audit compared all 43 base-table objects in the two full DuckDB builds. The repository's `compare-builds --exact` command is the supported repeatable procedure for published-object equality and is implemented so exact differences are evaluated inside DuckDB rather than materialized into Python.

## Final rule

Stage 1 is frozen as the accepted data foundation for subsequent deliverables. New dashboard/analysis work should consume the published marts and must preserve the semantic boundary documented here.
