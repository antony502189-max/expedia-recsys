# Semantic trip-date policy

## Why this layer exists

The Expedia source contains dates that are syntactically valid and therefore parse successfully,
but are not credible for the observed 2013–2014 event period. Confirmed examples include check-in
years 2057, 2557 and 2558, negative lead times, checkout before check-in and stays longer than one
year.

These rows are not technical parse failures. They remain in `stg_train_accepted` and
`fct_hotel_interactions` so that raw-to-fact reconciliation remains exact. They are isolated only
from calculations whose interpretation depends on credible trip chronology.

## Conservative safety bounds

The versioned analytics contract defines:

```text
maximum_lead_time_days = 730
maximum_stay_nights = 365
```

The limits are intentionally generous. They are not claims about typical traveller behaviour and
must not be used as business segmentation thresholds. Their sole purpose is to prevent
century-scale or otherwise implausible dates from contaminating calendar, seasonality and
booking-window objects while retaining the legitimate long tail.

Changing either value is a schema-contract change and requires two new reproducibility builds.

## Row-level fields

`fct_hotel_interactions` preserves the original parsed values and adds:

- `is_chronologically_valid_lead_time`;
- `is_chronologically_valid_stay_dates`;
- `is_plausible_lead_time`;
- `is_plausible_stay_dates`;
- `is_plausible_trip_dates`;
- `trip_date_quality`.

`trip_date_quality` is mutually exclusive and exhaustive:

```text
missing_checkin
checkin_before_event
lead_time_out_of_scope
missing_checkout
checkout_not_after_checkin
stay_out_of_scope
plausible
```

The legacy compatibility flags `has_valid_lead_time` and `has_valid_stay_dates` now mean
semantically plausible under the versioned contract, not merely parseable and chronologically
positive.

## Date dimension

`dim_date` is a role-playing date dimension built from:

1. every observed event date;
2. check-in dates with a plausible lead time;
3. checkout dates with a plausible complete trip chronology.

Parse-valid out-of-scope trip dates do not expand the date spine. The dimension additionally marks
whether each day is observed as an event, plausible check-in or plausible checkout date.

## Date-dependent marts

- `dm_checkin_seasonality` uses only rows with `is_plausible_lead_time = true`;
- `dm_booking_window` uses only rows with `is_plausible_trip_dates = true`;
- `dm_travel_patterns` computes lead-time and stay summaries only inside the semantic bounds;
- interaction, destination, market, route and user-activity totals continue to include every
  accepted source row.

This separation prevents silent row loss and prevents anomalous trip dates from distorting
calendar-based conclusions.

## Quality reporting and gates

`dm_data_quality_summary` publishes counts and shares for every `trip_date_quality` class.
Automated validation requires:

- every fact row has exactly one date-quality class;
- class counts reconcile to the complete interaction fact;
- `dim_date` exactly matches the eligible semantic date bounds;
- check-in seasonality reconciles to plausible check-ins;
- booking-window totals reconcile to plausible complete trips;
- out-of-scope dates cannot expand the date spine.

The presence of source anomalies is reported rather than hidden. A build fails only when the
classification, exclusion or reconciliation logic is inconsistent.
