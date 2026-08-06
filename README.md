# Expedia Product Analytics

Проект строит воспроизводимый аналитический слой на полном датасете Expedia Hotel Recommendations: типизированные данные, факт-таблицы, измерения, dashboard-ready витрины, контроль качества и manifest сборки.

## Цель текущего этапа

Реализован первый итоговый артефакт проекта:

1. структура витрин и документированная логика их сборки;
2. физические DuckDB-таблицы и Parquet-файлы под будущий дашборд и аналитические выводы;
3. единый словарь метрик;
4. data-quality слой и автоматические reconciliation checks.

ML-модели, Kaggle submissions и MAP@5 не являются целью этой ветки.

## Архитектура

```text
data/raw/*.csv
    -> data/processed/*.parquet
    -> analytics.fct_hotel_interactions
    -> analytics.fct_search_contexts
    -> analytics.dim_*
    -> analytics.dm_*
    -> data/analytics/expedia_analytics.duckdb
    -> data/marts/*.parquet
```

Главное ограничение источника: отсутствуют `session_id` и `search_request_id`. Поэтому `fct_search_contexts` использует детерминированный proxy поискового контекста. Это явно отражено в названиях метрик и документации.

## Подготовка источников

Требуются Python 3.11+, `uv` и исходные файлы в `data/raw`:

```text
train.csv или train.csv.gz
test.csv или test.csv.gz
destinations.csv или destinations.csv.gz
```

```powershell
uv sync --group dev
uv run expedia-recsys --threads 7 --memory-limit 32GB prepare
```

## Полная сборка витрин

Для Dell Precision 7710 / 64 GB RAM:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_product_analytics.ps1 `
  -Threads 7 `
  -MemoryLimit 32GB
```

Либо по шагам:

```powershell
uv run expedia-analytics --threads 7 --memory-limit 32GB build
uv run expedia-analytics validate
uv run expedia-analytics inspect
```

## Результаты

```text
data/analytics/expedia_analytics.duckdb
data/marts/fct_hotel_interactions.parquet
data/marts/fct_search_contexts.parquet
data/marts/dim_*.parquet
data/marts/dm_*.parquet
artifacts/analytics/build_manifest.json
artifacts/analytics/validation_report.json
```

## Основные витрины

- `dm_product_daily`, `dm_product_monthly` — состояние продукта;
- `dm_segment_daily`, `dm_segment_monthly` — device/package/traveller/lead-time/stay/distance/channel/site/lifecycle;
- `dm_destination_performance`, `dm_destination_monthly` — спрос и booking rate направлений;
- `dm_travel_patterns` — поведение по типам поездок;
- `dm_user_profile`, `dm_user_cohort_monthly` — пользовательская активность и когорты;
- `dm_data_quality_summary`, `dm_data_quality_daily` — качество данных.

## Документация

- `docs/marts_architecture.md` — архитектура, lineage и гранулярность;
- `docs/metric_dictionary.md` — формулы и ограничения метрик;
- SQL каждой таблицы находится в `sql/analytics/` и является исполняемой документацией.

## Проверки

```powershell
uv run ruff check .
uv run pytest
uv run expedia-analytics validate
```

Сборка атомарная: рабочая DuckDB заменяется только после успешного создания всех витрин и прохождения quality gates.
