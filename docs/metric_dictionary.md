# Словарь метрик

> Статус: финальный словарь Stage 1. Термины ниже синхронизированы с accepted data model и published marts.

## Единицы анализа

| Термин | Определение |
|---|---|
| `logged interaction` | одна принятая строка train с click/booking outcome |
| `weighted interaction` | interaction с весом, восстановленным из валидного `cnt` |
| `proxy context` | детерминированный request-like proxy для identified user; это не реальный session/search id |
| `user-day` | identified user × observed event date |
| `booking row` | logged interaction с `is_booking = 1` |
| `booking-bearing proxy context` | proxy context с хотя бы одной booking row |
| `booking user-day` | user-day с хотя бы одним booking interaction |

## Основные outcome metrics

### `booking_interaction_share`

```text
booking_rows / interaction_rows
```

Где:

- numerator: количество booking rows;
- denominator: количество зарегистрированных click/booking interactions.

Это **не** search-to-booking conversion и не checkout conversion.

### `weighted_booking_event_share`

```text
weighted_booking_events / weighted_interactions
```

Использует валидный event weight на основе исходного `cnt`. Не заменяет physical-row metric, а публикуется как отдельная sensitivity measure.

### `booking_bearing_proxy_context_share`

```text
booking_bearing_proxy_contexts / proxy_search_contexts
```

Только для identified users и только на детерминированном proxy grain.

Обязательное ограничение: proxy context не является доказанной сессией/поисковым запросом.

### `proxy_interaction_coverage`

Доля logged interactions, которые могут быть отнесены к identified-user proxy context population.

Используется рядом с proxy-context outcome, чтобы denominator coverage был явным.

### `booking_user_day_share`

```text
booking_user_days / observed_user_days
```

Daily user-day outcome для identified users.

### `booking_user_share`

Доля identified users с booking activity внутри конкретного опубликованного monthly observation window.

Это не customer conversion и не population-level Expedia KPI.

## Volume metrics

| Метрика | Смысл |
|---|---|
| `interaction_rows` | число физических logged interaction rows |
| `booking_rows` | число строк с `is_booking = 1` |
| `weighted_interactions` | сумма event weights |
| `proxy_search_contexts` | число deterministic proxy contexts |
| `observed_user_days` | число identified user-day observations |
| `observed_active_users` | identified users, наблюдавшиеся в соответствующем периоде |

## Segment metrics

`dm_segment_daily` и `dm_segment_monthly` публикуются в long format:

```text
period × segment_type × segment_value
```

Для каждого сегмента rate должен вычисляться из additive components:

```text
SUM(booking_rows) / SUM(interaction_rows)
```

Нельзя делать `AVG(booking_interaction_share)` между группами с разными denominators.

## Destination / market metrics

`dm_destination_performance`, `dm_hotel_market_performance` и `dm_booking_window` содержат outcome вместе с uncertainty/support metadata.

Ключевые правила:

- всегда сохранять numerator и denominator;
- использовать Wilson confidence interval для binomial share;
- не делать сильных выводов по sparse cells без учёта support;
- destination и hotel market не считать отношением one-to-one: используется явный many-to-many bridge.

## Travel metrics

### Lead time

```text
check-in date - event date
```

Используется только при корректной временной семантике и дополнительно сегментируется по contract boundaries.

### Stay nights

```text
checkout date - check-in date
```

Невалидные/неправдоподобные trip dates не подменяются нулями и учитываются в data-quality layer.

### Traveller segment

Contract-defined категории solo / couple / family / group / unknown на основе party composition.

## Observed recurrence

`dm_observed_recurrence` описывает повторно наблюдаемую активность identified users в пределах окна датасета.

```text
observed_recurrence_share
```

Правила интерпретации:

- first observed ≠ registration/acquisition;
- отсутствие пользователя ≠ churn;
- right-censored cells остаются `NULL`, а не искусственным нулём;
- термин `retention_rate` не используется.

## Data-quality metrics

### `missing_share`

Доля строк, где поле отсутствует/невалидно в соответствующей DQ-витрине.

### `affected_share`

Доля proxy population, затронутая конкретным ambiguity type.

### Booking-population drift

Train и test не объединяются в одну product-outcome population. Drift сравнивает booking-event populations и не называется product-traffic drift.

## Запрещённые интерпретации

На основании Stage 1 нельзя корректно публиковать как фактические продуктовые KPI:

- search-to-booking conversion;
- checkout conversion;
- CTR показов;
- revenue / GMV / margin / average check;
- cancellations;
- registration-based retention;
- churn;
- causal uplift без эксперимента.

Все dashboard и analytical-summary формулировки должны описывать только предоставленную историческую competition-выборку и указывать реальный denominator.
