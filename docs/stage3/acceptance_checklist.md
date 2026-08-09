# Stage 3 — Acceptance Checklist

## Цель

Пункт 3 считается закрытым только когда Analytical Summary не просто написан, а прослеживается до принятых данных и не нарушает semantic contract проекта.

## A. Scope

- [x] Описано, что происходит в historical sample.
- [x] Выделены сильные стороны.
- [x] Выделены слабые места / зоны риска.
- [x] Сформулированы точки роста.
- [x] Зафиксированы наиболее важные выводы команды.
- [x] Stage 4 A/B design не смешан со Stage 3.

## B. Evidence

- [x] Overall headline KPI связан с numerator/denominator.
- [x] Time trend содержит и volume, и outcome.
- [x] Device gap подтверждён counts/rates.
- [x] Package gap подтверждён counts/rates.
- [x] Traveller differences подтверждены counts/rates и planning data.
- [x] Booking-window extremes имеют strong support.
- [x] Destination candidates сопровождаются support и Wilson CI.
- [x] Missingness и semantic-date quality явно указаны.
- [x] Recurrence сопровождается observable cohort count и censoring caveat.
- [x] Evidence register создан.

## C. Semantic safety

- [x] `booking_interaction_share` не назван conversion rate.
- [x] Proxy contexts не названы sessions.
- [x] Observed recurrence не названа retention.
- [x] First observed не трактуется как registration/acquisition.
- [x] Destination/market candidates не названы доказанными defects.
- [x] Observational gaps не названы causal effects.
- [x] Test population drift не назван ordinary product traffic drift.

## D. Statistical safety

- [x] Published rates агрегируются через `SUM(numerator)/SUM(denominator)`.
- [x] Sparse entities не используются без support threshold.
- [x] Wilson intervals применяются на entity grain.
- [x] Distinct users не суммируются между месяцами.
- [x] Right-censored recurrence cells не превращаются в zero.

## E. Что ещё нужно перед финальным merge

- [ ] Сверить формулировки Summary с фактически реализованным Dashboard/BI после финальной сборки визуалов.
- [ ] Проверить, что headline values в BI совпадают с Stage 2 validation controls.
- [ ] При наличии export/screenshots добавить ссылки из Summary на соответствующие Dashboard pages/visual IDs.
- [ ] Провести финальный manual review wording: observed vs causal.
- [ ] Создать PR `feature/analytical-summary -> main` только после этих проверок.

## Текущий вердикт

**Stage 3 content foundation: READY.**

**Stage 3 final acceptance: PENDING DASHBOARD CROSS-CHECK.**
