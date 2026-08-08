# Правила качества данных

> Статус: финальный blocking quality contract Stage 1.

## Принцип

Плохие/неполные записи не удаляются молча. Raw values сохраняются, parsing/domain failures попадают в quarantine, а аналитические anomalies публикуются через validity flags и DQ marts.

## Source completeness и reconciliation

Для каждого источника обязательно:

```text
raw = accepted + quarantine
```

Проверяется не только row count, но и content-multiset reconciliation по каноническим fingerprints с multiplicity.

Источники:

- train;
- test;
- destinations.

## Blocking quality gates

Build не публикуется, если нарушено хотя бы одно из условий:

1. raw/accepted/quarantine reconciliation;
2. content multiset reconciliation;
3. `fct_hotel_interactions` не соответствует accepted train population;
4. proxy fact не сходится с identified interaction population;
5. `fct_user_day` не сходится с proxy-context population;
6. daily/monthly interaction totals не сходятся с fact;
7. booking numerators не сходятся с fact;
8. destination/market/route/bridge populations не reconcile;
9. хотя бы один published rate выходит за `[0, 1]`;
10. numerator отрицателен или превышает denominator;
11. Wilson interval некорректен;
12. `dim_date` содержит gap;
13. daily и monthly outcomes расходятся;
14. хотя бы один segment family не сходится с общей population;
15. published grain не уникален;
16. обязательный non-quarantine object пуст;
17. right-censored recurrence cell содержит выдуманное значение;
18. published schema содержит запрещённые metric terms;
19. quarantine rate выше contract threshold;
20. proxy multimarket ambiguity выше contract threshold;
21. semantic trip-date gates не проходят.

## Quarantine

Quarantine сохраняет:

- raw values;
- deterministic row identity;
- explicit reject reasons.

На принятом full-data build:

- train: 0 quarantined rows;
- test: 1 quarantined row;
- destinations: 0 quarantined rows.

Единственная test row была вручную проверена и корректно отклонена из-за invalid `srch_ci` parse (`2161-10-00`).

## Non-blocking analytical observations

Следующие состояния не обязательно означают corrupted source row и поэтому обычно сохраняются в accepted population с явными flags/DQ metrics:

- отсутствующий `user_id`;
- missing check-in/check-out;
- invalid/plausibility issue в lead time;
- checkout не позже check-in;
- missing distance;
- необычная party composition;
- missing destination/hotel market;
- missing/nonpositive `cnt`;
- proxy-context ambiguity;
- missingness drift;
- train/test booking-population drift.

Это предотвращает скрытый selection bias.

## Statistical safety

Rate marts должны хранить additive numerator и denominator.

Для sparse destination/market/booking-window cells проверяются Wilson intervals и support metadata.

BI должен пересчитывать rate после aggregation:

```text
SUM(numerator) / SUM(denominator)
```

## Semantic safety

Published contract запрещает термины, создающие неподдерживаемые claims, включая:

- conversion;
- retention;
- revenue;
- GMV;
- CTR;
- churn.

Допустимые формулировки должны описывать только предоставленную historical competition sample и реальную единицу анализа.

## Reproducibility / acceptance

Quality gates являются необходимым, но не достаточным условием final acceptance. Для accepted Stage 1 дополнительно выполнены:

- две независимые full-data сборки;
- одинаковые source/contract hashes;
- clean Git metadata в build manifests;
- exact reproducibility audit;
- manual verification representative rows/headline totals/quarantine;
- итоговый `FINAL_ACCEPTANCE.json` с `verdict = YES`.
