from __future__ import annotations

import numpy as np

from expedia_recsys.geo_fusion import _merge_at, _policy_grid, _source_gate


def test_merge_at_inserts_geo_without_duplicates() -> None:
    result = _merge_at(
        [5, 8, 2, 99, 82],
        [8, 37, 22],
        geo_count=2,
        insert_after=1,
    )
    assert result == [5, 8, 37, 2, 99]


def test_policy_grid_is_non_empty_and_unique() -> None:
    policies = _policy_grid()
    assert len(policies) == 576
    assert len(set(policies)) == len(policies)


def test_source_gate_modes() -> None:
    source_ids = np.asarray([1, 2, 4, 6], dtype=np.int16)
    assert _source_gate(source_ids, "all").tolist() == [True, True, True, True]
    assert _source_gate(source_ids, "exact_only").tolist() == [True, False, False, False]
    assert _source_gate(source_ids, "precise").tolist() == [True, True, False, True]
