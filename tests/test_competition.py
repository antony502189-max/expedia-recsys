from expedia_recsys.competition import SOURCES, _batch_ranges, source_feature_names


def test_source_feature_names_are_unique_and_complete() -> None:
    names = source_feature_names()
    assert len(names) == len(SOURCES) * 4
    assert len(names) == len(set(names))
    assert "src_01_score" in names
    assert "src_12_present" in names


def test_batch_ranges_cover_interval_without_overlap() -> None:
    assert list(_batch_ranges(0, 10, 4)) == [(0, 4), (4, 8), (8, 10)]
