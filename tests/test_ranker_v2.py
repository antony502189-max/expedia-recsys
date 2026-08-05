from __future__ import annotations

import pandas as pd
import pytest

from expedia_recsys.ranker_v2 import BlendWeights, _legacy_rank, _weight_grid


def test_weight_grid_contains_pure_components() -> None:
    weights = set(_weight_grid())
    assert BlendWeights(model=1.0, heuristic=0.0, legacy=0.0) in weights
    assert BlendWeights(model=0.0, heuristic=1.0, legacy=0.0) in weights
    assert BlendWeights(model=0.0, heuristic=0.0, legacy=1.0) in weights
    assert all(
        item.model + item.heuristic + item.legacy == pytest.approx(1.0)
        for item in weights
    )


def test_legacy_rank_prefers_stronger_source() -> None:
    frame = pd.DataFrame(
        {
            "row_id": [0, 0, 0],
            "candidate_cluster": [10, 20, 30],
            "combined_score": [3.0, 2.0, 1.0],
            "src_01_present": [0, 1, 0],
            "src_01_rank": [0, 1, 0],
            "src_02_present": [0, 0, 0],
            "src_02_rank": [0, 0, 0],
            "src_03_present": [0, 0, 0],
            "src_03_rank": [0, 0, 0],
            "src_05_present": [0, 0, 0],
            "src_05_rank": [0, 0, 0],
            "src_10_present": [0, 0, 0],
            "src_10_rank": [0, 0, 0],
            "src_12_present": [1, 1, 1],
            "src_12_rank": [1, 2, 3],
        }
    )
    assert _legacy_rank(frame).tolist() == [2, 1, 3]
