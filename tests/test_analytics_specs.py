from pathlib import Path

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.specs import MART_SPECS


def test_mart_names_and_sql_files_are_unique() -> None:
    names = [spec.name for spec in MART_SPECS]
    sql_files = [spec.sql_file for spec in MART_SPECS]
    assert len(names) == len(set(names))
    assert len(sql_files) == len(set(sql_files))


def test_dependency_order_starts_with_facts_and_dimensions() -> None:
    names = [spec.name for spec in MART_SPECS]
    assert names[:5] == [
        "fct_hotel_interactions",
        "fct_search_contexts",
        "dim_date",
        "dim_destination",
        "dim_user_first_seen",
    ]
    assert all(spec.grain and spec.description for spec in MART_SPECS)


def test_analytics_paths_are_project_relative(tmp_path: Path) -> None:
    paths = AnalyticsPaths.from_root(tmp_path)
    assert paths.train_path == tmp_path / "data" / "processed" / "train.parquet"
    assert paths.database_path == (
        tmp_path / "data" / "analytics" / "expedia_analytics.duckdb"
    )
    assert paths.sql_dir == tmp_path / "sql" / "analytics"
