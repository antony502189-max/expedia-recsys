# Expedia Product Analytics — обработанные данные и аналитические витрины

Первый итоговый артефакт проекта завершён: репозиторий содержит воспроизводимый слой обработанных данных и BI-ready витрин для дальнейшего дашборда и аналитических выводов.

## Статус

**Stage 1: COMPLETE**

Проверенная полная сборка:

- build A: `20260807T103804Z`;
- build B: `20260807T121247Z`;
- full-data reconciliation: PASS;
- manual verification: PASS;
- exact reproducibility audit: **43/43 base-table objects identical**;
- final acceptance: **YES**.

PR с реализацией Stage 1: `#2 Product analytics: final processed-data product and analytical marts`.

## Корректная интерпретация

Competition-датасет содержит зарегистрированные click/booking-взаимодействия, но не все поиски, показы, сессии, шаги оформления, оплаты и отмены.

Основной публикуемый outcome:

```text
booking_interaction_share = booking_rows / logged_interaction_rows
```

Это характеристика предоставленной исторической competition-выборки, а не полная продуктовая воронка и не Expedia-wide KPI. Дополнительные user/proxy metrics публикуются только с явным denominator и coverage.

Запрещённые трактовки: search-to-booking conversion, checkout conversion, retention, churn, revenue, GMV и causal uplift без отдельного источника данных/эксперимента.

## Финальная архитектура

```text
data/raw/train.csv[.gz]
data/raw/test.csv[.gz]
data/raw/destinations.csv[.gz]
  -> raw string landing
  -> accepted typed staging + row-preserving quarantine
  -> interaction, identified proxy-context and user-day facts
  -> date, origin, destination and segment dimensions
  -> destination-market bridge
  -> BI-safe dashboard/analysis marts
  -> immutable DuckDB + versioned Parquet + validation manifest
```

Реализованы:

- length-prefixed SHA-256 fingerprints и multiplicity-aware reconciliation точных дубликатов;
- гарантия `raw = accepted + quarantine` для каждого источника;
- content-multiset reconciliation;
- отдельная семантика physical row, `cnt`, proxy-context и user-day;
- уникальные grain keys для опубликованных объектов;
- additive numerators/denominators в rate marts;
- Wilson confidence intervals и statistical support для sparse breakdowns;
- missingness drift, proxy ambiguity и train/test booking-population drift;
- immutable build directories и атомарный `LATEST_BUILD.json`;
- SHA-256 исходников, контракта, lockfile, базы и Parquet-файлов;
- logical checksums и exact multiset comparison между независимыми сборками;
- автоматические quality gates и бинарный final acceptance evaluator.

## Основные слои

### Landing / staging

- `raw.*_landing` — исходные строки без потери значений;
- `staging.stg_*_accepted` — типизированные записи;
- `staging.quarantine_*` — отклонённые записи с raw values и reject reasons;
- reconciliation metadata — доказательство сохранности содержимого.

### Core

- `analytics.fct_hotel_interactions` — одно зарегистрированное click/booking interaction;
- `analytics.fct_proxy_search_contexts` — детерминированный request-like proxy только для identified users;
- `analytics.fct_user_day` — user × observed event day.

### Dimensions / bridge

- `dim_date`;
- `dim_origin`;
- `dim_destination`;
- `dim_segment_definition`;
- `bridge_destination_hotel_market`.

### BI marts

Витрины покрывают:

- sample activity daily/monthly;
- interaction outcomes daily/monthly;
- proxy-context outcomes daily/monthly;
- identified user-day outcomes daily/monthly;
- long-format segments daily/monthly;
- destinations, hotel markets и origin→destination routes;
- travel patterns, check-in seasonality и booking window;
- observed recurrence с right-censoring;
- missingness, proxy ambiguity, booking-population drift и data quality.

Подробные grain и семантика: `docs/marts_architecture.md`, `docs/data_dictionary.md`, `docs/metric_dictionary.md`.

## Установка

Нужны Python 3.11+, `uv` и исходные Expedia-файлы в `data/raw`.

```powershell
uv sync --frozen --group dev
```

## Полная сборка

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\run_product_analytics.ps1" `
  -Threads 7 `
  -MemoryLimit "32GB"
```

Либо напрямую:

```powershell
uv run --frozen expedia-analytics --threads 7 --memory-limit 32GB build-final
uv run --frozen expedia-analytics validate-final
uv run --frozen expedia-analytics inspect-final
```

## Reproducibility

Для двух независимых build ID:

```powershell
uv run --frozen expedia-analytics compare-builds <left_build_id> <right_build_id> --exact
```

Exact mode сначала проверяет schema/row-count consistency, затем для каждой опубликованной таблицы доказывает multiset equality через `EXCEPT ALL` без материализации различий в Python.

## Final acceptance

```powershell
Copy-Item config\manual_verification.example.json artifacts\analytics\manual_verification.json
# заполнить JSON после проверки representative rows, headline totals и quarantine

uv run --frozen expedia-analytics acceptance-status `
  <left_build_id> `
  <right_build_id> `
  --manual-verification artifacts\analytics\manual_verification.json
```

Авторитетный результат сохраняется в:

```text
artifacts/analytics/FINAL_ACCEPTANCE.json
```

Для принятой Stage 1 сборки получен `verdict = YES`.

## Физические результаты

```text
data/analytics/<build_id>/expedia_analytics.duckdb
data/marts/<build_id>/...
artifacts/analytics/<build_id>/build_manifest.json
artifacts/analytics/<build_id>/validation_report.json
artifacts/analytics/<build_id>/analytics_contract_snapshot.json
artifacts/analytics/<build_id>/SUCCESS.json
data/analytics/LATEST_BUILD.json
artifacts/analytics/FINAL_ACCEPTANCE.json
```

Большие generated DB/Parquet-файлы не хранятся в Git. В Git находится код, контракт, SQL, тесты и документация; готовые витрины передаются команде отдельным data handoff.

## Quality contract

Build публикуется только если выполняются blocking checks, включая:

- source completeness и content reconciliation;
- grain uniqueness;
- fact/mart reconciliation;
- daily ↔ monthly consistency;
- reconciliation каждого segment family;
- rates в `[0, 1]` и numerator ≤ denominator;
- корректные Wilson intervals;
- continuous date spine;
- корректное right-censoring;
- quarantine/proxy ambiguity thresholds;
- отсутствие запрещённых продуктовых терминов в published contract.

История требований и закрытие red-team blockers: `docs/third_red_team_audit.md`.
