# Архитектура обработанных данных и витрин

## Цель слоя данных

Слой данных превращает 37+ млн агрегированных логов Expedia в воспроизводимую аналитическую модель, пригодную для дашборда и продуктовых выводов. Сборка выполняется DuckDB без загрузки полного датасета в pandas.

```text
Kaggle CSV
  -> data/processed/*.parquet
  -> analytics.fct_hotel_interactions
  -> analytics.fct_search_contexts
  -> analytics.dim_*
  -> analytics.dm_*
  -> data/marts/*.parquet
  -> data/analytics/expedia_analytics.duckdb
```

## Две факт-таблицы

### `fct_hotel_interactions`

Гранулярность: одна строка исходного `train.csv`. Поле `cnt` — количество похожих событий в контексте той же пользовательской сессии, поэтому сохраняются одновременно физическое число строк и `event_weight`.

### `fct_search_contexts`

В источнике нет `session_id` и `search_request_id`. Детерминированный `search_context_key` строится из пользователя, времени, параметров поездки, устройства, канала и направления. Это proxy поискового контекста, а не доказанная сессия.

Основная продуктовая метрика:

```text
booking_context_rate = contexts с хотя бы одним booking / все contexts
```

Она не называется полной checkout-конверсией: в датасете отсутствуют показы, реальный session id и шаги оформления.

## Витрины

| Витрина | Гранулярность | Назначение |
|---|---|---|
| `dm_product_daily` | дата | Ежедневное состояние продукта |
| `dm_product_monthly` | месяц | Месячная динамика |
| `dm_segment_daily` | дата × тип сегмента × значение | Основные продуктовые разрезы |
| `dm_segment_monthly` | месяц × тип сегмента × значение | Быстрые месячные BI-запросы |
| `dm_destination_performance` | направление | Спрос, booking rate, opportunity quadrant |
| `dm_destination_monthly` | месяц × направление | Сезонность направлений |
| `dm_travel_patterns` | месяц × travel-сегменты | Поведение по типу поездки |
| `dm_user_profile` | пользователь | Частота, бронирования и lifecycle |
| `dm_user_cohort_monthly` | cohort × activity month | Когортная активность |
| `dm_data_quality_summary` | правило качества | Полный DQ-отчёт |
| `dm_data_quality_daily` | дата | Качество во времени |

## Сегментация

- устройство: mobile / desktop / unknown;
- пакет: package / standalone / unknown;
- путешественник: solo / couple / family / group / unknown;
- lead time: same day, 1–7, 8–30, 31–90, 91–180, 181+;
- stay: 1, 2–3, 4–7, 8–14, 15+ ночей;
- distance: технические интервалы исходного поля; единица измерения источником не названа;
- lifecycle: new / returning относительно первого наблюдаемого события.

## Воспроизводимость

Сборка:

- создаёт новую DuckDB во временном файле и заменяет рабочую только после quality gates;
- атомарно заменяет Parquet каждого mart;
- сохраняет SQL SHA-256, row count, диапазон дат, размер файла и время расчёта;
- сверяет facts и marts;
- не удаляет raw и processed данные.

## Физические артефакты

```text
data/analytics/expedia_analytics.duckdb
data/marts/*.parquet
artifacts/analytics/build_manifest.json
artifacts/analytics/validation_report.json
```
