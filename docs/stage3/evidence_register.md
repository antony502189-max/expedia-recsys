# Stage 3 — Evidence Register

## Назначение

Этот реестр связывает каждый headline conclusion Analytical Summary с фактической витриной, метрикой, support/uncertainty и ограничением интерпретации.

Source of truth: accepted build `20260807T121247Z`.

| ID | Наблюдение | Evidence | Основной mart / artifact | Проверка устойчивости | Ограничение |
|---|---|---|---|---|---|
| E01 | Overall booking interaction share = 7,9657% | 3 000 693 / 37 670 293 | `dm_interaction_outcome_monthly` / accepted totals | numerator/denominator reconcile to Stage 1 | Не conversion rate полного funnel |
| E02 | Volume растёт, outcome в Dec-2014 ниже Jan-2013 | 771 174 → 2 927 318 interactions; 8,9337% → 6,7334% | `dm_interaction_outcome_monthly`, `dm_sample_activity_monthly` | показывать volume и outcome совместно | Jan-2013 partial; возможен composition shift |
| E03 | Mobile ниже desktop | 5,8572% vs 8,2945%; gap -2,4373 pp | `dm_segment_monthly`, family `device` | strong support; проверить monthly stability | Association, не causal device effect |
| E04 | Package ниже standalone | 4,3747% vs 9,1557%; gap -4,7809 pp | `dm_segment_monthly`, family `package` | strong support; декомпозиция по traveller/lead/stay | Package intent отличается от standalone |
| E05 | Solo выше остальных traveller segments | Solo 12,3575%; Couple 6,8699%; Family 7,1428%; Group 7,0305% | `dm_segment_monthly`, `dm_travel_patterns` | traveller family имеет strong support | Traveller mix связан с planning horizon |
| E06 | Planning window имеет большой spread | same-day×1-night 19,1490%; 181–730×15–365 1,3756% | `dm_booking_window` | все 30 valid cells strong support; Wilson CI available | Intent/confounding; не causal lead-time effect |
| E07 | Traveller planning horizon различается | Solo ~36,3; Couple ~57,5; Family ~61,2; Group ~62,2 lead days | `dm_travel_patterns` | interaction-weighted values | Averages должны агрегироваться с весами |
| E08 | Destination 8791 — high-volume low-outcome candidate | 619 520 interactions; 2,9607%; CI 2,9188–3,0032% | `dm_destination_performance` | strong support + Wilson upper bound ниже overall | Investigation candidate, не defect |
| E09 | Destination 11439 — второй пример high-volume candidate | 367 301 interactions; 2,5584%; CI 2,5078–2,6100% | `dm_destination_performance` | strong support + narrow CI | Анонимизированная entity; причина неизвестна |
| E10 | Distance missingness высокая | 35,9036% overall; daily max ~45,9595% | `dm_missingness_daily` | primary visuals от distance не зависят | Distance segmentation требует coverage caveat |
| E11 | Trip-date semantics почти полностью valid | 99,4657% plausible; checkout<=checkin warning 0,3865% | `dm_data_quality_summary` | Stage 1 quality gates PASS | Invalid/missing buckets не скрывать полностью |
| E12 | Observed recurrence заметна, но censored | age1 30,6724% / 23 cohorts; age3 23,0019% / 21; 47,92% grid censored | `dm_observed_recurrence` | сравнивать одинаковый age и только uncensored cells | Не retention после регистрации |
| E13 | Destination/market long tail sparse | 2 970 strong destinations; 1 526 strong markets; routes mostly low support | destination/market/route marts | strong threshold >=1000, adequate >=100 | Нельзя ранжировать sparse entities по raw rate |
| E14 | Stage 1 data foundation reproducible | final acceptance YES; failures 0; 43/43 exact | `FINAL_ACCEPTANCE.json`, reproducibility proof | independent builds | Качество data layer не устраняет selection bias source dataset |

## Интерпретационный стандарт

Каждый вывод в итоговом summary должен удовлетворять пяти условиям:

1. Есть явный numerator/denominator или entity-level statistic.
2. Grain соответствует вопросу.
3. Для sparse entity выводов проверен support и, где доступно, Wilson interval.
4. Distinct users не суммируются по времени.
5. Формулировка отделяет observed association от causal explanation.

## Термины, которые запрещено подменять

- `booking_interaction_share` ≠ conversion rate;
- `proxy context` ≠ session;
- `first observed month` ≠ acquisition month;
- `observed recurrence` ≠ retention;
- `investigation_candidate` ≠ product defect;
- train/test booking population drift ≠ обычный traffic drift.
