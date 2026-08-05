from expedia_recsys.ranker import CATEGORICAL_FEATURES, RANKER_FEATURES


def test_ranker_features_are_unique() -> None:
    assert len(RANKER_FEATURES) == len(set(RANKER_FEATURES))
    assert set(CATEGORICAL_FEATURES).issubset(RANKER_FEATURES)


def test_ranker_contains_all_source_signals() -> None:
    for source_id in range(1, 13):
        prefix = f"src_{source_id:02d}"
        assert f"{prefix}_score" in RANKER_FEATURES
        assert f"{prefix}_share" in RANKER_FEATURES
        assert f"{prefix}_rank" in RANKER_FEATURES
        assert f"{prefix}_present" in RANKER_FEATURES
