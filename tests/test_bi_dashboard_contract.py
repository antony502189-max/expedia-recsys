from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from expedia_analytics.bi_dashboard import BI_CONTRACT_VERSION, MART_SPECS, SOURCE_BUILD_ID


def test_dashboard_contract_covers_all_documented_visuals() -> None:
    """The checked-in contract remains complete without requiring local data exports."""
    assert BI_CONTRACT_VERSION == "1.0.0"
    assert SOURCE_BUILD_ID == "20260807T121247Z"
    assert {spec["page"] for spec in MART_SPECS.values()} == {1, 2, 3, 4, 5}
    assert sorted(visual for spec in MART_SPECS.values() for visual in spec["visuals"]) == list(
        range(1, 26)
    )
    assert all(
        spec["sources"] and spec["grain"] and spec["purpose"] for spec in MART_SPECS.values()
    )


def test_secondary_segments_have_stable_valid_ordering() -> None:
    """Channel and site are approved segment families, not invalid buckets."""
    path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "bi"
        / "20260807T121247Z"
        / "bi_segments_monthly.parquet"
    )
    if not path.exists():
        pytest.skip("BI delivery export is not available in this test environment")
    con = duckdb.connect()
    try:
        invalid, missing_sort = con.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE NOT is_valid_segment),
                COUNT(*) FILTER (WHERE segment_sort_order IS NULL)
            FROM read_parquet(?)
            WHERE segment_type IN ('channel', 'site')
            """,
            [str(path)],
        ).fetchone()
    finally:
        con.close()
    assert invalid == 0
    assert missing_sort == 0
