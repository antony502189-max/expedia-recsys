# Stage 3 — Analytical Summary

## Статус

**DRAFT 1 — evidence-backed analytical summary.**

Источник истины: принятая Stage 1 full-data сборка `20260807T121247Z` и dashboard/BI-контракты Stage 2. Stage 1 имеет final acceptance `YES`, `0` failures и exact reproducibility `43/43`.

Этот документ описывает закономерности **в предоставленной historical competition sample Expedia**. Он не описывает весь текущий бизнес Expedia и не доказывает причинные эффекты.

---

## 1. Executive summary

В выборке наблюдается 37 670 293 logged click/booking interactions, из которых 3 000 693 — booking rows. Основной outcome `booking_interaction_share` равен 7,9657%.

Главная картина состоит не из одного «плохого» или «хорошего» KPI, а из нескольких устойчивых неоднородностей:

1. Объём наблюдаемых interactions заметно растёт по времени, но booking interaction share к концу окна ниже, чем в начале. Это требует анализа composition mix, а не трактовки как доказанного ухудшения продукта.
2. Mobile и package interactions имеют существенно более низкий observed outcome, чем desktop и standalone соответственно. Это наиболее очевидные сегментные зоны для дальнейшего исследования.
3. Traveller type и planning horizon сильно связаны с observed outcome. Особенно выделяются solo и короткие planning windows.
4. На уровне destinations существуют high-volume entities с outcome существенно ниже общего benchmark и с узкими Wilson intervals; это сильные кандидаты на диагностику, но не доказанные product defects.
5. Observed recurrence показывает заметное повторное появление identified users, однако почти половина cohort grid right-censored, поэтому late-age выводы без cohort context некорректны.
6. Data quality достаточна для текущего описательного анализа: Stage 1 принят, trip-date semantics покрывают 99,4657% interactions. При этом distance missingness высока — 35,9036%, поэтому distance нельзя делать ключевой продуктовой осью без отдельной оговорки.

---

## 2. Что происходит с наблюдаемым продуктовым поведением

### 2.1. Объём растёт, outcome не растёт вместе с ним

Наблюдаемая monthly activity увеличивается с 771 174 interactions в неполном январе 2013 года до 2 927 318 в декабре 2014 года. За тот же период monthly booking interaction share меняется с 8,9337% до 6,7334%, то есть примерно на -2,20 процентного пункта.

Это сильный сигнал для диагностики состава population: рост объёма сам по себе не означает улучшение outcome. Возможные объяснения включают изменение device/package/channel/site/traveller mix, destination mix или другие composition effects.

**Что можно утверждать:** объём выборки и observed outcome меняются в разных направлениях.

**Что нельзя утверждать:** что продукт Expedia деградировал именно из-за какой-либо функции или изменения интерфейса.

### 2.2. Device — заметная зона неоднородности

Desktop:

- 32 587 572 interactions;
- 2 702 986 booking rows;
- booking interaction share 8,2945%.

Mobile:

- 5 082 721 interactions;
- 297 707 booking rows;
- booking interaction share 5,8572%.

Абсолютная наблюдаемая разница — **-2,4373 п.п.** для mobile относительно desktop.

Mobile therefore является приоритетной зоной дальнейшего разложения: нужно проверить, сохраняется ли gap внутри traveller/package/lead-time и временных срезов, а также насколько он объясняется composition mix.

### 2.3. Package — самый крупный из простых segment gaps

Standalone:

- 28 293 998 interactions;
- 2 590 505 booking rows;
- 9,1557% booking interaction share.

Package:

- 9 376 295 interactions;
- 410 188 booking rows;
- 4,3747% booking interaction share.

Абсолютный gap — **-4,7809 п.п.** для package относительно standalone.

Это крупнейший из headline binary-segment gaps и поэтому одна из самых сильных точек для дальнейшей диагностики. Однако package trip может иметь принципиально другой intent, lead time, stay length и traveller composition, поэтому gap нельзя трактовать как причинный эффект package flow.

### 2.4. Traveller type показывает различное observed behaviour

Booking interaction share:

- Solo — 12,3575%;
- Couple — 6,8699%;
- Family — 7,1428%;
- Group — 7,0305%.

Solo находится примерно на +4,39 п.п. выше общего benchmark 7,9657%.

Одновременно планирование различается:

- Solo — около 36,3 valid lead days;
- Couple — около 57,5;
- Family — около 61,2;
- Group — около 62,2.

Это показывает, что traveller type связан не только с observed outcome, но и с planning horizon. Поэтому traveller и lead-time следует рассматривать совместно на уровне гипотез, но не смешивать grains произвольными additive joins.

### 2.5. Planning window — один из самых сильных behavioural signals

Valid `lead_time × stay` matrix содержит 30 ячеек, и каждая имеет strong support.

Два крайних примера:

- same-day × one-night — 145 488 booking rows / 759 768 interactions = **19,1490%**;
- 181–730 days × 15–365 nights — 505 / 36 710 = **1,3756%**.

Разница очень велика и подтверждается достаточным support. Это делает planning context ключевым объясняющим измерением при интерпретации других segment gaps.

Нельзя, однако, утверждать, что короткий lead time сам «вызывает» booking: это наблюдаемая ассоциация с пользовательским intent и trip context.

---

## 3. Сильные стороны наблюдаемого состояния

### 3.1. Есть крупные сегменты с высоким observed outcome

Solo и некоторые short-horizon planning cells демонстрируют outcome значительно выше общего benchmark. Это показывает, что в данных присутствуют контексты с высокой booking propensity среди logged interactions.

### 3.2. Аналитические сигналы статистически поддержаны

Для основных сегментов и всей 6×5 booking-window matrix support достаточен для устойчивых описательных сравнений. Для destinations и markets используются explicit support thresholds и Wilson intervals, что защищает от вывода по случайным 0%/100% sparse entities.

### 3.3. Data foundation надёжна

Stage 1 принят с `0` failures и exact reproducibility `43/43`. Это означает, что аналитический summary строится не на ad-hoc выгрузке, а на воспроизводимом data contract.

### 3.4. Trip-date semantics почти полностью покрыты

99,4657% interactions попадают в plausible trip-date semantics, поэтому основные travel analyses могут опираться на валидные planning buckets без существенной потери population.

---

## 4. Слабые места / зоны риска

### 4.1. Mobile gap

Mobile booking interaction share ниже desktop на 2,4373 п.п. Это high-volume segment, поэтому даже после учёта composition эффект может оставаться продуктово значимым. Требуется дальнейшее controlled decomposition.

### 4.2. Package gap

Package interactions имеют 4,3747% против 9,1557% у standalone. Разница велика и требует разложения по traveller, lead-time, stay, channel/site и времени.

### 4.3. High-volume destination underperformance candidates

Destination 8791:

- 619 520 interactions;
- 18 342 booking rows;
- 2,9607%;
- Wilson 95% CI: 2,9188%–3,0032%.

Destination 11439:

- 367 301 interactions;
- 2,5584%;
- Wilson 95% CI: 2,5078%–2,6100%.

Обе сущности существенно ниже overall benchmark 7,9657% при большом объёме и узкой statistical uncertainty. Их следует считать **investigation candidates**, а не product defects.

### 4.4. Sparse long tail

Из 59 455 destinations:

- 2 970 strong;
- 8 005 adequate;
- 48 480 low support.

Routes ещё более sparse: 3 768 350 из 3 810 666 route rows имеют low support. Поэтому ranking без support filtering способен породить ложные «лучшие» и «худшие» объекты.

### 4.5. Distance missingness

`orig_destination_distance` отсутствует примерно для 35,9036% interactions. Это не блокирует основные dashboard/summary выводы, но делает distance плохим кандидатом для primary segmentation без coverage-aware analysis.

### 4.6. Recurrence censoring

Observed recurrence:

- age 1 — 30,6724% для 23 observable cohorts;
- age 3 — 23,0019% для 21 observable cohorts;
- 276 из 576 cohort-grid cells (47,92%) right-censored.

Поэтому одну pooled recurrence curve нельзя интерпретировать как полноценную retention curve.

---

## 5. Точки роста для дальнейшего продуктового исследования

### Growth area A — Mobile experience

**Почему:** большой объём и устойчивый observed gap к desktop.

**Что исследовать дальше:** внутри-сегментный gap по package, traveller, lead-time, stay и event month; стабильность разницы; high-volume destinations на mobile.

### Growth area B — Package journey

**Почему:** самый крупный headline binary gap — примерно -4,78 п.п. к standalone.

**Что исследовать дальше:** связка package × traveller × lead-time × stay; различия по каналам и времени; не является ли observed gap следствием fundamentally different trip intent.

### Growth area C — Planning assistance for complex / long-horizon trips

**Почему:** booking-window spread очень большой; long-horizon/long-stay contexts имеют существенно более низкий observed outcome.

**Что исследовать дальше:** информационная сложность, выбор destination/market, traveller composition, package share и repeat activity для таких поездок.

### Growth area D — High-volume destination diagnostics

**Почему:** существуют destinations с сотнями тысяч interactions и outcome значительно ниже benchmark даже с narrow Wilson CI.

**Что исследовать дальше:** временная стабильность, market composition, device/package/traveller mix, route mix и наличие systematic differences.

### Growth area E — Returning identified-user experience

**Почему:** age-1 recurrence около 30,67%, но cohort dynamics и censoring требуют аккуратного анализа.

**Что исследовать дальше:** различия recurrence по доступным стабильным сегментам и связь повторной активности с observed booking outcome — только в пределах корректной observability.

---

## 6. Наиболее важные выводы команды

1. **Нельзя оценивать состояние только по объёму.** Interaction volume растёт, тогда как observed booking share к концу окна ниже; composition effects являются обязательной частью интерпретации.
2. **Mobile и package — наиболее очевидные high-volume investigation areas.** Их gaps достаточно велики, чтобы приоритизировать дальнейшее разложение.
3. **Planning context критичен.** Lead-time/stay и traveller type существенно связаны с observed outcome и могут объяснять часть headline segment gaps.
4. **Destination-level opportunity существует, но требует статистической дисциплины.** Используем strong support + Wilson CI; sparse tail не ранжируем как продуктовые проблемы.
5. **Нельзя превращать descriptive analytics в causal claims.** Этот этап формулирует подтверждённые наблюдения и зоны исследования; причинность должна проверяться отдельно.
6. **Нельзя называть `booking_interaction_share` conversion rate.** Denominator — logged click/booking interactions, а не полный search/impression funnel.
7. **Observed recurrence не является полноценной retention.** First observed month не равен acquisition, а right censoring должен оставаться явным.

---

## 7. Ограничения данных

Dataset не содержит полного набора:

- searches;
- impressions;
- real session/request identifier;
- checkout funnel;
- payments;
- cancellations;
- revenue / GMV;
- полного Expedia traffic.

Следовательно, нельзя делать утверждения о search-to-booking conversion, CTR, revenue uplift, churn или causal product impact.

Destination и hotel market — анонимизированные сущности с many-to-many relationship; их нельзя складывать или трактовать как одну и ту же географическую сущность.

---

## 8. Связь со Stage 4

Stage 3 **не проектирует A/B-тесты**. Он передаёт в Stage 4 только evidence-backed opportunity areas:

- mobile;
- package;
- complex/long-horizon planning;
- high-volume destination diagnostics;
- returning identified-user experience.

На Stage 4 каждая из этих зон должна быть преобразована в отдельную продуктовую гипотезу с target audience, primary metric, guardrails, experiment design и decision rule.
