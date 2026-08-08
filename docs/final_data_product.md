# Финальная реализация обработанных данных и витрин

## Статус

**Stage 1 accepted. Final verdict: YES.**

Полная реализация закрытого acceptance contract прошла две независимые full-data сборки, автоматические quality gates, exact reproducibility audit и ручную reconciliation-проверку.

Accepted builds:

- `20260807T103804Z`;
- `20260807T121247Z`.

Финальный audit result:

```text
EXACT REPRODUCIBILITY: 43/43 base-table objects identical
MANUAL VERIFICATION: PASSED
FINAL ACCEPTANCE: YES
FAILURES: 0
```

## Семантическая граница

Источник является исторической competition-выборкой зарегистрированных click/booking-взаимодействий. Это не полный журнал поисков, показов, checkout, оплат, отмен или всего трафика Expedia.

Основной наблюдаемый outcome:

```text
booking_interaction_share = booking_rows / logged_interaction_rows
```

Secondary sensitivity metric для identified users:

```text
booking_bearing_proxy_context_share =
booking-bearing deterministic proxy contexts / all deterministic proxy contexts
```

Ни одна из этих величин не трактуется как полная search-to-booking conversion.

## Data flow

```text
raw CSV strings
  -> raw.*_landing
  -> staging.stg_*_accepted + staging.quarantine_*
  -> analytics.fct_hotel_interactions
  -> analytics.fct_proxy_search_contexts
  -> analytics.fct_user_day
  -> dimensions and bridge tables
  -> BI-safe marts
  -> immutable versioned DuckDB and Parquet outputs
```

Каждая raw row представлена ровно один раз в accepted staging либо quarantine. Canonical length-prefixed SHA-256 fingerprints и duplicate occurrence используются для multiset reconciliation без зависимости от порядка выполнения.

## Core objects

| Объект | Гранулярность | Назначение |
|---|---|---|
| `stg_train_accepted` | fingerprint × duplicate occurrence | typed train rows |
| `quarantine_train` | fingerprint × duplicate occurrence | raw values + reject reasons |
| `stg_test_accepted` | test id | isolated test booking population |
| `quarantine_test` | fingerprint × duplicate occurrence | rejected test rows |
| `stg_destinations_accepted` | destination id | typed destination latent features |
| `quarantine_destinations` | fingerprint × duplicate occurrence | rejected destination rows |
| `fct_hotel_interactions` | interaction id | one logged click/booking interaction |
| `fct_proxy_search_contexts` | proxy context id | deterministic request-like proxy for identified users |
| `fct_user_day` | user × event date | observed user activity grain |
| `dim_date` | date | continuous observed date spine |
| `dim_origin` | composite origin id | anonymized origin hierarchy |
| `dim_destination` | destination id | latent destination features |
| `dim_segment_definition` | segment type × value | stable BI labels/order |
| `bridge_destination_hotel_market` | destination × market | explicit many-to-many relationship |

## Published marts

Слой витрин включает:

- sample activity daily/monthly;
- logged interaction outcomes daily/monthly;
- proxy-context sensitivity daily/monthly;
- identified user-day outcomes daily/monthly;
- long-format segment daily/monthly;
- destination, destination-month и hotel-market outcomes;
- anonymized origin-to-destination routes;
- travel patterns, check-in seasonality и booking-window analysis;
- observed recurrence с cohort-age/right-censoring semantics;
- missingness drift и proxy-context ambiguity;
- train-booking против test-booking population drift;
- source/staging/semantic data-quality summary.

Каждая rate-витрина хранит additive numerator и denominator. Destination/market/booking-window objects содержат Wilson confidence intervals и support metadata.

## Physical delivery

Каждый build записывается в новые immutable directories:

```text
data/analytics/<build_id>/expedia_analytics.duckdb
data/marts/<build_id>/...
artifacts/analytics/<build_id>/build_manifest.json
artifacts/analytics/<build_id>/validation_report.json
artifacts/analytics/<build_id>/analytics_contract_snapshot.json
artifacts/analytics/<build_id>/SUCCESS.json
```

`LATEST_BUILD.json` обновляется атомарно только после quality gates. Предыдущий successful build остаётся доступным для rollback/audit.

Manifest содержит:

- SHA-256 raw sources, contract, lockfile, database и каждого Parquet;
- Git commit/branch/dirty flag;
- Python/platform/DuckDB version;
- row counts, schemas, grains и logical checksums;
- build configuration и elapsed time;
- full validation report.

## Exact reproducibility

Быстрая проверка сравнивает logical multiset checksums.

Exact mode дополнительно:

1. сравнивает schema;
2. проверяет равенство row counts;
3. выполняет внутри DuckDB `EXCEPT ALL` emptiness proof без материализации full-table differences в Python.

При одинаковом количестве строк пустой `LEFT EXCEPT ALL RIGHT` математически достаточен для доказательства equality мультимножеств.

```powershell
uv run --frozen expedia-analytics compare-builds <left> <right> --exact
```

Для accepted Stage 1 отдельный audit проверил 43/43 base-table objects.

## Binary acceptance

`acceptance-status` является authoritative машинным механизмом проверки принятия artifact one. Он требует одновременно:

1. два successful full-data build;
2. clean Git tree в manifests;
3. identical source и contract SHA-256;
4. все quality gates;
5. identical logical checksums;
6. exact published-table multiset equality;
7. manual verification representative rows, headline totals и quarantine;
8. reviewer + UTC timestamp.

Шаблон:

```text
config/manual_verification.example.json
```

Команда:

```powershell
uv run --frozen expedia-analytics acceptance-status `
  <left_build_id> `
  <right_build_id> `
  --manual-verification artifacts\analytics\manual_verification.json
```

Manual verification reader поддерживает как plain UTF-8, так и Windows UTF-8 BOM.

Результат сохраняется в:

```text
artifacts/analytics/FINAL_ACCEPTANCE.json
```

Принятый Stage 1 имеет `verdict = YES`.
