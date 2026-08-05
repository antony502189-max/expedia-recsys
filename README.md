# Expedia Hotel Recommendations — этап 1

Первый воспроизводимый этап проекта:

1. чтение исходных Kaggle CSV/CSV.GZ без загрузки всего датасета в pandas;
2. нормализация типов и преобразование в Parquet через DuckDB;
3. временная валидация: история до cutoff, бронирования после cutoff;
4. MAP@5 и Recall@5;
5. сильный частотный baseline из шести источников кандидатов;
6. генерация `submission_stage1.csv`.

## Источники кандидатов

Приоритет кандидатов фиксирован:

1. страна + регион + город пользователя + hotel market + точное расстояние;
2. город пользователя + точное расстояние;
3. user + destination + hotel country + hotel market;
4. destination + hotel country + hotel market;
5. hotel country + hotel market;
6. глобально популярные hotel cluster.

Клики и бронирования имеют разные веса. Более свежие события получают больший вес.

## 1. Установка

Требуется Python 3.11+ и `uv`.

```powershell
uv sync --group dev
```

## 2. Данные

Положите в `data/raw`:

```text
train.csv или train.csv.gz
test.csv или test.csv.gz
destinations.csv или destinations.csv.gz
```

При настроенном Kaggle API можно использовать:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/download_data.ps1
```

## 3. Подготовка Parquet

```powershell
uv run expedia-recsys --memory-limit 8GB prepare
```

Результат:

```text
data/processed/train.parquet
data/processed/test.parquet
data/processed/destinations.parquet
```

## 4. Временная валидация

По умолчанию история заканчивается 31 июля 2014 года, а validation начинается 1 августа 2014 года и содержит только бронирования.

```powershell
uv run expedia-recsys --memory-limit 8GB validate --cutoff 2014-08-01
```

Результат:

```text
artifacts/validation_metrics.json
artifacts/validation_predictions.csv
```

Основная метрика — `map_at_5`. Для одной правильной метки в строке она совпадает со средним reciprocal rank правильного hotel cluster в топ-5.

## 5. Submission

```powershell
uv run expedia-recsys --memory-limit 8GB submit
```

Результат:

```text
artifacts/submission_stage1.csv
```

## 6. Полный запуск

```powershell
uv run expedia-recsys --memory-limit 8GB all --cutoff 2014-08-01
```

Если в ноутбуке меньше 12–16 ГБ RAM, установите лимит `6GB`. DuckDB сможет использовать диск, но обработка займёт больше времени.

## 7. Проверки

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Что считается завершением этапа 1

- исходные данные преобразуются одной командой;
- validation не использует события из будущего;
- получена зафиксированная MAP@5;
- сформирован корректный CSV с пятью уникальными hotel cluster для каждой строки;
- код проходит тесты и статический анализ.
