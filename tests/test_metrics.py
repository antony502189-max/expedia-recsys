import pytest

from expedia_recsys.metrics import map_at_k, reciprocal_rank_at_k


def test_reciprocal_rank_at_5() -> None:
    assert reciprocal_rank_at_k(7, [7, 1, 2, 3, 4]) == 1.0
    assert reciprocal_rank_at_k(7, [1, 7, 2, 3, 4]) == 0.5
    assert reciprocal_rank_at_k(7, [1, 2, 3, 4, 7]) == 0.2
    assert reciprocal_rank_at_k(7, [1, 2, 3, 4, 5]) == 0.0


def test_map_at_5() -> None:
    score = map_at_k([7, 9], [[7, 1, 2, 3, 4], [1, 9, 2, 3, 4]])
    assert score == pytest.approx(0.75)


def test_map_at_5_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        map_at_k([], [])
