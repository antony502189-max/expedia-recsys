# Expedia Hotel Recommendations

Воспроизводимый pipeline для Kaggle Expedia Hotel Recommendations:

- CSV → типизированный Parquet через DuckDB;
- честная временная валидация;
- MAP@5;
- 12 источников кандидатов;
- memory-safe пакетная обработка;
- LightGBM LambdaRank для ранжирования 20 кандидатов;
- генерация Kaggle submission.

## Зафиксированные результаты

На временном holdout с `cutoff=2014-08-01`:

| Модель | MAP@5 | Recall@20 |
|---|---:|---:|
| Stage-1 heuristic | 0.51258 | — |
| 12-source candidate heuristic | 0.51136 | 0.89777 |

Первый Kaggle submission дал Public MAP@5 `0.50376` и Private MAP@5 `0.50008`.

Высокий Recall@20 означает, что правильный hotel cluster уже присутствует среди кандидатов почти в 90% запросов. LambdaRank обучается выбирать и правильно упорядочивать эти кандидаты.

## Установка

Требуется Python 3.11+ и `uv`.

```powershell
uv sync --group dev
```

## Данные

Файлы Kaggle размещаются в `data/raw` и не коммитятся:

```text
train.csv
test.csv
destinations.csv
sample_submission.csv
```

## Подготовка данных

```powershell
uv run expedia-recsys --memory-limit 8GB prepare
```

Результат:

```text
data/processed/train.parquet
data/processed/test.parquet
data/processed/destinations.parquet
```

## Stage-1 baseline

```powershell
uv run expedia-recsys --memory-limit 8GB validate --cutoff 2014-08-01
uv run expedia-recsys --memory-limit 8GB submit
```

## Расширенный генератор кандидатов

Используются:

1. exact geo + distance;
2. city + distance;
3. user + destination + market;
4. user + destination;
5. destination + market;
6. user + market;
7. destination;
8. destination + check-in month;
9. market + check-in month;
10. country + market;
11. user history;
12. global popularity.

Проверка:

```powershell
uv run expedia-recsys --threads 4 --memory-limit 8GB competition-validate `
    --cutoff 2014-08-01
```

## LambdaRank

Команда строит признаки для пар `query × candidate`, обучает LightGBM LambdaRank, использует раннюю остановку на отдельном временном окне и затем считает MAP@5 на полном holdout.

```powershell
uv run expedia-recsys --threads 4 --memory-limit 8GB ranker-validate `
    --train-start 2014-05-01 `
    --cutoff 2014-08-01 `
    --max-train-queries 100000 `
    --max-eval-queries 25000
```

Артефакты:

```text
artifacts/ranker_model.txt
artifacts/ranker_model_metadata.json
artifacts/ranker_feature_importance.csv
artifacts/ranker_validation_metrics.json
artifacts/ranker_validation_predictions.csv
```

Для компьютера с ограниченной RAM начните с:

```powershell
uv run expedia-recsys --threads 4 --memory-limit 8GB ranker-validate `
    --max-train-queries 50000 `
    --max-eval-queries 15000
```

## Submission ranker-модели

После успешной валидации:

```powershell
uv run expedia-recsys --threads 4 --memory-limit 8GB ranker-submit
```

Результат:

```text
artifacts/submission_ranker.csv
```

Отправка:

```powershell
uvx kaggle competitions submit expedia-hotel-recommendations `
    -f artifacts/submission_ranker.csv `
    -m "LightGBM LambdaRank 12-source candidates"
```

## Проверки

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
