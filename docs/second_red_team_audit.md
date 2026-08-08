# Second red-team audit — historical findings

## Status

This file preserves the second pre-acceptance review. Its findings are **historical and resolved** in the accepted Stage 1 implementation.

Current authoritative status:

```text
Stage 1: COMPLETE
Final acceptance: YES
Exact reproducibility audit: 43/43 base-table objects identical
```

Final closure report: `docs/third_red_team_audit.md`.

## Findings that drove the final design

### 1. Recommendation preparation was not sufficient as an analytical raw layer

Resolved by introducing:

- analytics-specific raw string landing;
- typed accepted staging;
- row-preserving quarantine;
- explicit reject reasons;
- raw/accepted/quarantine reconciliation;
- content-multiset reconciliation.

### 2. Segment design required explicit profiling and contract semantics

Resolved through source profiling, fixed segment definitions, stable sort metadata and separate semantic trip-date policy.

### 3. Competition data is not audited Expedia-wide telemetry

Resolved through an explicit semantic scope. Published outcomes describe only the supplied historical sample and do not claim complete search/session/checkout/revenue coverage.

### 4. Search/session conversion could not be reconstructed

Resolved by using supported terminology such as:

```text
booking_interaction_share
booking_bearing_proxy_context_share
booking_user_day_share
observed_recurrence_share
```

Unsupported public terms are blocked by the contract.

### 5. User lifecycle required censoring-aware language

Resolved through `first_observed_*` and `observed_recurrence` semantics plus right-censoring metadata. Registration, churn and generic retention claims are not published.

### 6. Destination geography was many-to-many

Resolved with `bridge_destination_hotel_market`; modal geography is not treated as a stable destination attribute.

### 7. Origin hierarchy required composite identity

Resolved with deterministic composite `origin_id` based on anonymized country/region/city hierarchy.

### 8. Train and test represent different analytical populations

Resolved by isolating test from train product-outcome marts and publishing only booking-population drift comparisons where appropriate.

### 9. Missingness could represent instrumentation/logging changes

Resolved through daily missingness/validity drift marts and downstream coverage metadata.

### 10. Sparse rates needed uncertainty/support

Resolved through additive numerators/denominators, Wilson confidence intervals and support metadata for relevant breakdowns.

### 11. Reproducibility required immutable physical delivery

Resolved through build IDs, immutable DuckDB/Parquet directories, source/contract/lockfile hashes, logical checksums, atomic latest pointer and exact cross-build comparison.

### 12. SQL semantics needed end-to-end testing

Resolved through synthetic end-to-end builds that exercise staging, facts, dimensions, marts, semantic-date rules and reproducibility across different thread counts.

## Final note

This audit should not be read as an open TODO list. It documents why the final Stage 1 architecture is stricter than the initial prototype. Current implementation and acceptance evidence are documented in:

- `docs/final_data_product.md`;
- `docs/third_red_team_audit.md`;
- `README.md`.
