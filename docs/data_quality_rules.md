# Правила качества данных

## Blocking quality gates

Сборка завершается ошибкой, если:

1. число строк `fct_hotel_interactions` не равно числу строк prepared train;
2. в fact появились пустые `event_date`;
3. `is_booking` вышел за домен 0/1;
4. `event_weight < 1`;
5. сумма daily contexts не равна числу строк `fct_search_contexts`;
6. сумма daily booking contexts не равна числу contexts с `has_booking`;
7. доли выходят за диапазон 0–1;
8. любая обязательная fact/dimension/mart пуста.

## Non-blocking observations

Они сохраняются в DQ-витринах, но не удаляются:

- отсутствующий `user_id`;
- пропуски check-in/check-out;
- отрицательный lead time;
- checkout не позже check-in;
- отсутствующая distance;
- некорректные adults/children/rooms;
- отсутствующие destination или hotel market;
- `cnt` отсутствует или неположителен.

Такой подход сохраняет сырой факт и не создаёт скрытый selection bias. Для продуктовых метрик используются явные validity-флаги.
