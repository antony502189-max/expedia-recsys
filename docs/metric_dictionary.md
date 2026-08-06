# Словарь метрик

## Единицы анализа

| Термин | Определение |
|---|---|
| interaction row | физическая строка `train.csv` после типизации |
| weighted interaction | `event_weight`, восстановленный из `cnt` |
| search context | детерминированный proxy одного поискового запроса |
| booking context | search context с хотя бы одной строкой `is_booking = 1` |

## Метрики

| Метрика | Формула | Ограничение |
|---|---|---|
| `search_contexts` | `COUNT(*)` по `fct_search_contexts` | Proxy: нет session/search id |
| `booking_contexts` | contexts с `has_booking` | Бронирование внутри proxy-контекста |
| `booking_context_rate` | booking contexts / all contexts | Не impression-to-booking conversion |
| `active_users` | `COUNT(DISTINCT user_id)` | Только наблюдаемые пользователи |
| `new_users` | пользователь активен в дату/месяц first-seen | Не дата регистрации |
| `returning_users` | активность после first-seen | Ограничено окном датасета |
| `interaction_rows` | сумма физических строк | Не учитывает `cnt` |
| `weighted_interactions` | `SUM(event_weight)` | Оценка фактического объёма событий |
| `mobile_context_share` | mobile contexts / all contexts | На уровне search-context proxy |
| `package_context_share` | package contexts / all contexts | На уровне search-context proxy |
| `contexts_per_active_user` | contexts / active users | Интенсивность активности |
| `avg_lead_time_days` | среднее check-in минус event date | Невалидные даты исключены |
| `avg_stay_nights` | среднее checkout минус check-in | Невалидные даты исключены |

## Запрещённые интерпретации

По этому датасету нельзя корректно считать GMV, выручку, маржу, средний чек, отмены, CTR показов, конверсию отдельных шагов checkout и causal uplift без эксперимента.
