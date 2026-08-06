from __future__ import annotations

from expedia_recsys.geo_leak import (
    CONFIDENCE_GRID,
    SUPPORT_GRID,
    _merge_top5,
    _parse_prediction,
    _reciprocal_rank,
    _thresholds,
)


def test_merge_top5_deduplicates_and_preserves_order() -> None:
    assert _merge_top5([5, 2, 5], [2, 9, 1, 8]) == [5, 2, 9, 1, 8]


def test_prediction_parsing_and_reciprocal_rank() -> None:
    predictions = _parse_prediction("91 0 31 96 48")
    assert predictions == [91, 0, 31, 96, 48]
    assert _reciprocal_rank(31, predictions) == 1 / 3
    assert _reciprocal_rank(7, predictions) == 0.0


def test_threshold_grid_is_complete() -> None:
    grid = list(_thresholds())
    assert len(grid) == len(CONFIDENCE_GRID) * len(SUPPORT_GRID)
    assert (0.35, 1) in grid
    assert (0.95, 10) in grid
