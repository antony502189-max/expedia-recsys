# Архитектура обработанных данных и витрин

> Статус: архитектурный прототип. Перед финальной сборкой необходимо закрыть обязательные замечания из [`max_quality_audit.md`](max_quality_audit.md). Текущие таблицы нельзя представлять как окончательный слой данных до полного прогона на 37+ млн строк и прохождения расширенных quality gates.

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

Гранулярность: одна строка исходного `train.csv`. Поле `cnt` — количество похожих событий в контексте той же пользовательской сессии. До финальной версии raw `cnt`, валидный similar-event count и физическое число строк должны трактоваться раздельно.

### `fct_search_contexts`

В источнике нет `session_id` и `search_request_id`. Детерминированный `search_context_key` строится из пользователя, времени, параметров поездки, устройства, канала и направления. Это proxy поискового контекста, а не доказанная сессия.

Временная чувствительная метрика:

```text
booking_bearing_proxy_context_share = proxy contexts с хотя бы одним booking / все proxy contexts
```

Она не является полной checkout-конверсией: в датасете отсутствуют показы, реальный session id и шаги оформления. Основной наблюдаемый outcome должен рассчитываться также непосредственно на interaction-row grain.

## Витрины прототипа

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

Окончательный состав и семантика определены в `max_quality_audit.md` и будут расширены специализированными outcome-, channel-, market-, route-, seasonality- и retention-витринами.

## Сегментация

- устройство: mobile / desktop / unknown;
- пакет: package / standalone / unknown;
- путешественник: solo / couple / family / group / unknown;
- lead time: same day, 1–7, 8–30, 31–90, 91–180, 181+;
- stay: 1, 2–3, 4–7, 8–14, 15+ ночей;
- distance: интервалы исходного поля только на hotel-interaction grain; контекстный `ANY_VALUE(distance)` запрещён;
- lifecycle: new / returning / unknown относительно первого наблюдаемого события.

Границы сегментов должны быть подтверждены source profile и устойчивостью размера групп, а не только экспертно заданы.

## Воспроизводимость

Финальная сборка должна:

- создавать новую DuckDB во временном файле и заменять рабочую только после quality gates;
- писать весь набор Parquet в неизменяемую директорию конкретного build ID;
- обновлять `LATEST_BUILD.json` только после успешного завершения;
- сохранять предыдущий успешный build для rollback;
- сохранять SQL SHA-256, row count, grain uniqueness, диапазон дат, размер файла и время расчёта;
- сохранять версии Python/DuckDB, Git commit, source schema и source metadata;
- не удалять raw и processed данные.

## Физические артефакты

```text
data/analytics/expedia_analytics.duckdb
data/marts/<build_id>/*.parquet
data/marts/LATEST_BUILD.json
artifacts/analytics/build_manifest.json
artifacts/analytics/validation_report.json
artifacts/analytics/source_profile.json
```
