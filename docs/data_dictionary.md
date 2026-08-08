# Словарь аналитических данных

> Статус: финальный Stage 1 data dictionary. Имена синхронизированы с accepted schema contract.

## Landing / staging

### `raw.*_landing`

Raw-string representation исходных train/test/destinations. Используется для lossless audit и reconciliation.

### `staging.stg_train_accepted`

Гранулярность: `raw_row_fingerprint × duplicate_occurrence`.

Типизированные train rows, прошедшие parsing/domain checks.

### `staging.quarantine_train`

Та же row identity, но для rejected train rows. Хранит raw values и explicit reject reasons.

### `staging.stg_test_accepted`

Гранулярность: `id`.

Типизированная test booking-population. Не смешивается с product-outcome marts train.

### `staging.quarantine_test`

Rejected test rows с raw values и reject reasons.

### `staging.stg_destinations_accepted`

Гранулярность: `srch_destination_id`.

Destination latent features `d1-d149` после типизации.

### `staging.quarantine_destinations`

Rejected destination rows.

## Core facts

### `analytics.fct_hotel_interactions`

Гранулярность: `interaction_id`.

Одно принятое зарегистрированное click/booking interaction.

Ключевые группы полей:

- source identity / fingerprint;
- исходные Expedia train columns;
- `event_datetime`, `event_date`, `event_month`;
- physical-row и weighted-event semantics;
- `interaction_type` / booking flag;
- trip-date validity/quality;
- `lead_time_days`, `stay_nights`, party features;
- device/package/traveller/lead-time/stay segment labels;
- composite origin identity;
- destination / hotel geography identifiers.

Большой fact экспортируется partitioned по event year/month.

### `analytics.fct_proxy_search_contexts`

Гранулярность: `proxy_context_id`.

Детерминированный request-like proxy только для identified users.

Это не настоящий session/search id. В объекте публикуются interaction/booking components, coverage и ambiguity-safe context summaries.

### `analytics.fct_user_day`

Гранулярность: `user_id × event_date`.

Observed user activity по дням: interactions, proxy contexts и booking-bearing activity.

## Dimensions / bridge

### `analytics.dim_date`

Гранулярность: `date_day`.

Continuous observed date spine без gaps.

### `analytics.dim_origin`

Гранулярность: `origin_id`.

Deterministic composite key для anonymized `country × region × city` origin hierarchy.

### `analytics.dim_destination`

Гранулярность: `srch_destination_id`.

Latent destination features `d1-d149` и observed coverage metadata. Hotel market не считается функциональным атрибутом destination.

### `analytics.dim_segment_definition`

Гранулярность: `segment_type × segment_value`.

Stable BI labels и sort order для published segment families.

### `analytics.bridge_destination_hotel_market`

Гранулярность: `srch_destination_id × hotel_market`.

Observed many-to-many связь destination ↔ hotel market с additive interaction/booking components.

## Published marts

### `dm_sample_activity_daily`

Grain: `event_date`.

Daily coverage/activity supplied historical sample.

### `dm_sample_activity_monthly`

Grain: `event_month`.

Monthly sample coverage/activity.

### `dm_interaction_outcome_daily`

Grain: `event_date`.

Daily `booking_interaction_share` и weighted sensitivity components.

### `dm_interaction_outcome_monthly`

Grain: `event_month`.

Monthly logged-interaction outcome.

### `dm_proxy_context_daily`

Grain: `event_date`.

Proxy-context outcome + coverage for identified users.

### `dm_proxy_context_monthly`

Grain: `event_month`.

Monthly proxy-context sensitivity.

### `dm_user_day_daily`

Grain: `event_date`.

Observed identified-user-day activity and booking-user-day share.

### `dm_user_day_monthly`

Grain: `event_month`.

Monthly identified-user outcome.

### `dm_segment_daily`

Grain: `event_date × segment_type × segment_value`.

Long-format daily BI breakdowns. Rate строится из additive numerator/denominator.

### `dm_segment_monthly`

Grain: `event_month × segment_type × segment_value`.

Monthly long-format segment breakdowns.

### `dm_destination_performance`

Grain: `srch_destination_id`.

Destination outcome, support metadata и Wilson confidence interval.

### `dm_destination_monthly`

Grain: `event_month × srch_destination_id`.

Destination dynamics.

### `dm_hotel_market_performance`

Grain: `hotel_market`.

Hotel-market outcome + uncertainty/support.

### `dm_origin_destination_routes`

Grain: `origin_id × srch_destination_id`.

Observed anonymized route demand/outcome.

### `dm_travel_patterns`

Grain: `event_month × traveller_segment × lead_time_segment × stay_segment`.

Travel-pattern cube только на валидных trip-date semantics.

### `dm_checkin_seasonality`

Grain: `checkin_month × traveller_segment`.

Observed seasonality по check-in month / traveller type.

### `dm_booking_window`

Grain: `lead_time_segment × stay_segment`.

Planning horizon × stay duration outcome с uncertainty/support.

### `dm_observed_recurrence`

Grain: `first_observed_month × activity_month`.

Observed recurrence внутри dataset window. Right-censored cells не заполняются искусственными нулями.

### `dm_missingness_daily`

Grain: `event_date × field_name`.

Missingness/validity drift.

### `dm_proxy_context_ambiguity`

Grain: `ambiguity_type`.

Coverage и ambiguity diagnostics для proxy contexts.

### `dm_booking_population_drift`

Grain: `dataset × period_month × dimension_name × dimension_value`.

Train-booking vs test-booking population drift. Не product-traffic drift.

### `dm_booking_population_drift_summary`

Grain: `dimension_name`.

Summary distribution drift по измерениям.

### `dm_data_quality_summary`

Grain: `quality_rule`.

Source/staging/semantic DQ summary.

## BI aggregation rule

Для любой rate-витрины:

```text
correct rate = SUM(numerator) / SUM(denominator)
```

Нельзя усреднять готовые percentages между ячейками с разным denominator.

## Реестр и manifests

Полный machine-readable реестр объектов, grain, row counts, schemas, checksums и export paths сохраняется в build manifest:

```text
artifacts/analytics/<build_id>/build_manifest.json
```

Финальные semantics и ограничения метрик: `docs/metric_dictionary.md`.
