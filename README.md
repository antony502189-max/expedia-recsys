# Expedia Product Analytics — обработанные данные и аналитические витрины

Эта ветка реализует только первый итоговый артефакт проекта: воспроизводимый слой
обработанных данных и BI-ready витрины. Рекомендательные модели, Kaggle submissions и MAP@5
не входят в scope.

## Корректная интерпретация

Competition-датасет содержит зарегистрированные click/booking-взаимодействия, но не все поиски,
показы, сессии, шаги оформления, оплаты и отмены. Основной публикуемый outcome:

```text
booking_interaction_share = booking_rows / logged_interaction_rows
```

Это характеристика предоставленной исторической выборки, а не полная продуктовая воронка и не
Expedia-wide KPI. Отдельно публикуется secondary sensitivity metric для детерминированных
proxy-контекстов идентифицированных пользователей.

## Финальная архитектура

```text
data/raw/train.csv[.gz]
data/raw/test.csv[.gz]
data/raw/destinations.csv[.gz]
  -> raw string landing
  -> accepted typed staging + row-preserving quarantine
  -> interaction, identified proxy-context and user-day facts
  -> date, origin, destination and segment dimensions
  -> destination-market bridge
  -> dashboard/analysis marts
  -> immutable DuckDB + versioned Parquet + validation manifest
```

Реализованы:

- length-prefixed SHA-256 fingerprints и учёт multiplicity точных дубликатов;
- равенство `raw = accepted + quarantine`;
- content-multiset reconciliation;
- отдельная семантика физической строки, `cnt`, proxy-контекста и user-day;
- Wilson confidence intervals и support labels;
- missingness drift, proxy ambiguity и train/test booking-population drift;
- immutable build directories, rollback pointer и SHA-256 каждого Parquet;
- логические checksums и точное `EXCEPT ALL` сравнение двух сборок;
- автоматические quality gates и отдельный бинарный acceptance evaluator.

## Установка

Нужны Python 3.11+, `uv` и три исходных файла в `data/raw`.

```powershell
uv sync --group dev
```

## Полная сборка на проектном ноутбуке

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\run_product_analytics.ps1" `
  -Threads 7 `
  -MemoryLimit "32GB"
```

Скрипт запускает Ruff, тесты, опциональную сверку legacy-Parquet, source profile, immutable build,
повторную validation и печать registry.

## Команды

```powershell
uv run expedia-analytics --threads 7 --memory-limit 32GB build-final
uv run expedia-analytics validate-final
uv run expedia-analytics inspect-final
uv run expedia-analytics compare-builds <left_build_id> <right_build_id> --exact
```

Финальный бинарный вердикт после двух чистых сборок и ручной сверки:

```powershell
Copy-Item config\manual_verification.example.json artifacts\analytics\manual_verification.json
# заполнить JSON после проверки контрольных строк и итоговых чисел
uv run expedia-analytics acceptance-status `
  <left_build_id> `
  <right_build_id> `
  --manual-verification artifacts\analytics\manual_verification.json
```

Команда возвращает только `YES` после прохождения всех машинных и ручных критериев. В остальных
случаях она возвращает `NO` и закрытый список непройденных checks.

## Физические результаты

```text
data/analytics/<build_id>/expedia_analytics.duckdb
data/marts/<build_id>/...
artifacts/analytics/<build_id>/build_manifest.json
artifacts/analytics/<build_id>/validation_report.json
artifacts/analytics/<build_id>/analytics_contract_snapshot.json
artifacts/analytics/<build_id>/SUCCESS.json
data/analytics/LATEST_BUILD.json
artifacts/analytics/FINAL_ACCEPTANCE.json
```

## Blocking quality contract

Build публикуется только после выполнения всех проверок, включая:

- raw rows равны accepted плюс quarantine;
- raw и output multisets совпадают по fingerprint и multiplicity;
- все grain keys уникальны;
- факты и витрины сходятся по числителям и знаменателям;
- daily и monthly totals совпадают;
- каждый segment type независимо сходится с общей популяцией;
- rate лежат в `[0, 1]`, а числители не превышают знаменатели;
- Wilson intervals корректны;
- календарь непрерывен;
- right-censored recurrence cells не заполняются выдуманными нулями;
- quarantine и proxy ambiguity не превышают контрактные пороги;
- опубликованные имена не создают ложных продуктовых трактовок.

## Статус

Кодовая реализация финального контракта находится в ветке. Артефакт остаётся draft до полного
прогона на 37,6 млн строк, второго чистого прогона, точного сравнения двух DuckDB и ручной проверки.
После этого единственным авторитетным ответом является поле `verdict` в
`artifacts/analytics/FINAL_ACCEPTANCE.json`.

Подробности: `docs/final_data_product.md` и `docs/third_red_team_audit.md`.
