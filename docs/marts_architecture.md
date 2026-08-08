# Архитектура обработанных данных и витрин

> Статус: **FINAL / ACCEPTED**. Stage 1 прошёл полный data-run, quality gates, две независимые сборки, exact reproducibility audit и manual verification. Final acceptance: `YES`.

## Цель слоя данных

Слой данных превращает историческую Expedia competition-выборку в воспроизводимую аналитическую модель, пригодную для BI-дашборда и продуктовых выводов без повторной агрегации десятков миллионов строк в BI-инструменте.

```text
Kaggle CSV
  -> raw string landing
  -> typed accepted staging + quarantine
  -> analytical facts
  -> dimensions + bridge
  -> BI-safe marts
  -> immutable versioned DuckDB + Parquet
```

## Landing и staging

Каждая исходная строка сохраняется в raw landing и затем попадает ровно в одну из двух веток:

```text
raw row
  -> accepted staging
  -> quarantine + reject reasons
```

Контракт требует:

```text
raw = accepted + quarantine
```

Кроме арифметики строк выполняется content-multiset reconciliation по каноническим fingerprint с multiplicity.

## Core facts

### `fct_hotel_interactions`

Гранулярность: одно принятое зарегистрированное click/booking interaction.

Это не search и не session. Исходный `cnt` и физическая строка хранят раздельную семантику.

Большой fact экспортируется partitioned по году/месяцу.

### `fct_proxy_search_contexts`

Гранулярность: один детерминированный request-like proxy для identified user.

Источник не содержит настоящего `session_id`/`search_request_id`, поэтому proxy metrics всегда публикуются как sensitivity layer, а не как полноценная воронка.

### `fct_user_day`

Гранулярность: `user_id × event_date`.

Используется для identified-user activity и booking-user metrics с явным coverage.

## Dimensions и bridge

| Объект | Grain | Назначение |
|---|---|---|
| `dim_date` | date | continuous observed date spine |
| `dim_origin` | composite origin id | анонимизированная country/region/city иерархия |
| `dim_destination` | destination id | latent features `d1-d149` и покрытие |
| `dim_segment_definition` | segment type × value | стабильные BI labels и sort order |
| `bridge_destination_hotel_market` | destination × hotel market | явная many-to-many связь |

## Published marts

### Product / sample dynamics

| Mart | Grain | Назначение |
|---|---|---|
| `dm_sample_activity_daily` | day | daily sample coverage/activity |
| `dm_sample_activity_monthly` | month | monthly sample coverage/activity |
| `dm_interaction_outcome_daily` | day | booking share among logged interactions |
| `dm_interaction_outcome_monthly` | month | monthly interaction outcome |
| `dm_proxy_context_daily` | day | proxy-context sensitivity + coverage |
| `dm_proxy_context_monthly` | month | monthly proxy-context sensitivity |
| `dm_user_day_daily` | day | identified-user activity/outcome |
| `dm_user_day_monthly` | month | monthly identified-user outcome |

### Segments

| Mart | Grain | Назначение |
|---|---|---|
| `dm_segment_daily` | day × segment type × value | BI-safe daily breakdowns |
| `dm_segment_monthly` | month × segment type × value | BI-safe monthly breakdowns |

Published segment families include device, package, traveller, lead-time, stay, channel/site and other contract-defined categories. Rate marts carry additive numerators and denominators.

### Destination / market / routes

| Mart | Grain | Назначение |
|---|---|---|
| `dm_destination_performance` | destination | destination outcomes + Wilson uncertainty |
| `dm_destination_monthly` | month × destination | destination dynamics |
| `dm_hotel_market_performance` | hotel market | market outcomes + uncertainty |
| `dm_origin_destination_routes` | origin × destination | observed anonymized route demand/outcome |

### Travel behavior

| Mart | Grain | Назначение |
|---|---|---|
| `dm_travel_patterns` | month × traveller × lead-time × stay | multi-dimensional travel patterns |
| `dm_checkin_seasonality` | check-in month × traveller | seasonality |
| `dm_booking_window` | lead-time × stay | planning horizon / stay-length outcome |

### Observability / recurrence

| Mart | Grain | Назначение |
|---|---|---|
| `dm_observed_recurrence` | first observed month × activity month | observed recurrence with right-censoring |

Название intentional: это не registration-based retention и не churn model.

### Data quality / drift

| Mart | Grain | Назначение |
|---|---|---|
| `dm_missingness_daily` | day × field | missingness/validity drift |
| `dm_proxy_context_ambiguity` | ambiguity type | proxy coverage/ambiguity |
| `dm_booking_population_drift` | dataset × month × dimension × value | train-booking vs test-booking population drift |
| `dm_booking_population_drift_summary` | dimension | distribution drift summary |
| `dm_data_quality_summary` | quality rule | source/staging/semantic DQ summary |

## BI contract

Для rate-витрин BI должен агрегировать числитель и знаменатель, а затем пересчитывать rate:

```text
rate = SUM(numerator) / SUM(denominator)
```

Нельзя усреднять уже рассчитанные проценты между группами с разным объёмом.

Для sparse destination/market/booking-window breakdowns публикуются Wilson confidence intervals и support metadata.

## Physical design

Большие row-level факты partitioned по event year/month. Компактные агрегированные marts экспортируются отдельными Parquet-файлами с ZSTD compression.

Каждый успешный build имеет immutable директории:

```text
data/analytics/<build_id>/expedia_analytics.duckdb
data/marts/<build_id>/...
artifacts/analytics/<build_id>/build_manifest.json
artifacts/analytics/<build_id>/validation_report.json
artifacts/analytics/<build_id>/analytics_contract_snapshot.json
artifacts/analytics/<build_id>/SUCCESS.json
```

`LATEST_BUILD.json` обновляется атомарно только после прохождения quality gates. Предыдущие успешные build остаются доступны для rollback/audit.

## Reproducibility evidence

Для принятого Stage 1 выполнены две независимые полные сборки:

- `20260807T103804Z`;
- `20260807T121247Z`.

Отдельный exact audit подтвердил равенство **43/43 base-table objects**. Final manual verification также пройдена; итоговый acceptance: `YES`.
