# Финальная реализация обработанных данных и витрин

## Бинарный статус

Код в этой ветке реализует закрытый контракт из `third_red_team_audit.md`. Артефакт получает
финальный статус только после полного локального build, всех автоматических gates, второй чистой
сборки с идентичными данными и ручной reconciliation контрольных строк.

## Семантическая граница

Источник является исторической competition-выборкой зарегистрированных click/booking-
взаимодействий. Это не полный журнал поисков, показов, checkout, оплат, отмен или всего трафика
Expedia. Основной наблюдаемый outcome:

```text
booking_interaction_share = booking_rows / logged_interaction_rows
```

Secondary metric для идентифицированных пользователей:

```text
booking_bearing_proxy_context_share =
booking-bearing deterministic proxy contexts / all deterministic proxy contexts
```

Ни одна из этих величин не трактуется как полная search-to-booking воронка.

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

Каждая raw-строка представлена ровно один раз в accepted staging либо quarantine. Канонические
length-prefixed SHA-256 fingerprints и duplicate occurrence используются для multiset
reconciliation без зависимости от случайного порядка выполнения.

## Core objects

| Объект | Гранулярность | Назначение |
|---|---|---|
| `stg_train_accepted` | fingerprint × duplicate occurrence | Типизированные train-строки |
| `quarantine_train` | fingerprint × duplicate occurrence | Raw-значения и reject reasons |
| `stg_test_accepted` | test id | Отдельная booking-population test |
| `fct_hotel_interactions` | interaction id | Одно зарегистрированное взаимодействие |
| `fct_proxy_search_contexts` | proxy context id | Request-like proxy только для known user |
| `fct_user_day` | user × event date | Надёжная user-activity гранулярность |
| `dim_origin` | composite origin id | Анонимизированная country/region/city комбинация |
| `dim_destination` | destination id | d1-d149 и наблюдаемое покрытие |
| `bridge_destination_hotel_market` | destination × market | Явная many-to-many связь |

## Published marts

Слой витрин включает:

- sample activity daily/monthly;
- logged interaction outcomes daily/monthly;
- proxy-context sensitivity daily/monthly;
- identified user-day outcomes daily/monthly;
- long-format device/package/traveller/lead-time/stay/channel/site segments;
- destination, destination-month и hotel-market outcomes;
- анонимизированные origin-to-destination routes;
- travel patterns, check-in seasonality и booking-window analysis;
- observed recurrence с полной cohort-age сеткой и censoring metadata;
- missingness drift и proxy-context ambiguity;
- train-booking против test-booking population drift;
- source/staging data-quality summary.

Каждая rate-витрина хранит additive numerator и denominator. Destination и market objects содержат
Wilson confidence intervals и уровни statistical support.

## Physical delivery

Каждый build записывается в новые immutable директории:

```text
data/analytics/<build_id>/expedia_analytics.duckdb
data/marts/<build_id>/...
artifacts/analytics/<build_id>/build_manifest.json
artifacts/analytics/<build_id>/validation_report.json
artifacts/analytics/<build_id>/analytics_contract_snapshot.json
artifacts/analytics/<build_id>/SUCCESS.json
```

`LATEST_BUILD.json` обновляется атомарно только после всех quality gates. Предыдущий успешный build
остаётся доступным для rollback.

Manifest содержит:

- SHA-256 raw sources, contract, lockfile, database и каждого Parquet;
- Git commit, branch и dirty flag;
- Python, platform и DuckDB version;
- row counts, schemas, grains и logical checksums;
- configuration и elapsed time;
- полный validation report.

## Exact reproducibility

Быстрая проверка сравнивает multiset checksums. Финальная проверка подключает обе DuckDB и для
каждого published object выполняет двусторонний `EXCEPT ALL`. Это проверяет точное равенство схем и
мультимножеств строк, а не только совпадение агрегированного hash.

```powershell
uv run expedia-analytics compare-builds <left> <right> --exact
```

## Binary acceptance

`acceptance-status` является единственным авторитетным механизмом смены ответа с `NO` на `YES`.
Он требует одновременно:

1. два успешных build на полном train/test/destinations;
2. clean Git tree в обоих manifest;
3. одинаковые source и contract SHA-256;
4. все quality gates;
5. одинаковые logical checksums;
6. нулевой symmetric difference для каждого published table;
7. ручную проверку representative rows, headline totals и quarantine;
8. заполненный reviewer и UTC timestamp.

Шаблон ручной проверки:

```text
config/manual_verification.example.json
```

Команда:

```powershell
uv run expedia-analytics acceptance-status `
  <left_build_id> `
  <right_build_id> `
  --manual-verification artifacts\analytics\manual_verification.json
```

Результат сохраняется в:

```text
artifacts/analytics/FINAL_ACCEPTANCE.json
```

До появления `"verdict": "YES"` PR остаётся draft.
