# Словарь аналитических данных

## `fct_hotel_interactions`

Гранулярность: одна типизированная строка исходного `train.csv`.

| Поле | Смысл |
|---|---|
| `source_row_id` | технический номер строки в текущей сборке |
| `interaction_key` | технический hash взаимодействия |
| `search_context_key` | hash параметров поискового контекста |
| `event_datetime`, `event_date`, `event_month`, `event_week` | время взаимодействия |
| `source_cnt` | исходное `cnt` |
| `event_weight` | `GREATEST(COALESCE(cnt, 1), 1)` |
| `interaction_type` | click или booking |
| `lead_time_days` | check-in минус дата взаимодействия |
| `stay_nights` | checkout минус check-in |
| `party_size` | adults + children |
| `device_segment` | mobile / desktop / unknown |
| `package_segment` | package / standalone / unknown |
| `traveller_segment` | solo / couple / family / group / unknown |
| `lead_time_segment` | интервалы горизонта планирования |
| `stay_segment` | интервалы длительности проживания |
| `distance_segment` | технические интервалы distance |
| `has_valid_lead_time` | check-in не раньше события |
| `has_valid_stay_dates` | checkout позже check-in |

Все исходные поля train сохраняются. Аномальные строки не удаляются молча: они помечаются флагами и попадают в data-quality marts.

## `fct_search_contexts`

Гранулярность: один proxy поискового контекста.

Ключевые поля:

- параметры пользователя, устройства, канала и поездки;
- `interaction_rows`, `weighted_interactions`;
- `click_rows`, `weighted_clicks`;
- `booking_rows`, `weighted_bookings`;
- `has_booking`;
- число различных hotel clusters и markets;
- наиболее частая география отеля;
- забронированный cluster, когда он наблюдается.

## Измерения

- `dim_date` — полный календарь периода;
- `dim_destination` — `srch_destination_id`, latent-признаки `d1-d149`, наблюдаемая география и период активности;
- `dim_user_first_seen` — первая и последняя наблюдаемая дата пользователя.

## Dashboard marts

Полный реестр, гранулярность, row count, диапазоны дат и пути к Parquet сохраняются в `analytics.meta_mart_registry` и `artifacts/analytics/build_manifest.json`.
