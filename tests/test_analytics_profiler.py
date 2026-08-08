from pathlib import Path

import duckdb

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.profiler import profile_sources


def _write_synthetic_sources(root: Path) -> AnalyticsPaths:
    paths = AnalyticsPaths.from_root(root)
    paths.processed_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE train AS
            SELECT * FROM (VALUES
                (
                    TIMESTAMP '2014-01-01 10:00:00', 2::SMALLINT, 3::SMALLINT,
                    66::INTEGER, 1::INTEGER, 10::INTEGER, '100.0', 100.0::DOUBLE,
                    1001::BIGINT, 0::TINYINT, 0::TINYINT, 9::SMALLINT,
                    DATE '2014-02-01', DATE '2014-02-05', 2::SMALLINT, 0::SMALLINT,
                    1::SMALLINT, 500::INTEGER, 1::SMALLINT, 0::TINYINT, 2::INTEGER,
                    2::SMALLINT, 50::INTEGER, 100::INTEGER, 20::SMALLINT
                ),
                (
                    TIMESTAMP '2014-01-01 10:00:00', 2::SMALLINT, 3::SMALLINT,
                    66::INTEGER, 1::INTEGER, 10::INTEGER, '120.0', 120.0::DOUBLE,
                    1001::BIGINT, 0::TINYINT, 0::TINYINT, 9::SMALLINT,
                    DATE '2014-02-01', DATE '2014-02-05', 2::SMALLINT, 0::SMALLINT,
                    1::SMALLINT, 500::INTEGER, 1::SMALLINT, 1::TINYINT, 1::INTEGER,
                    2::SMALLINT, 50::INTEGER, 101::INTEGER, 21::SMALLINT
                ),
                (
                    TIMESTAMP '2014-01-02 12:00:00', 2::SMALLINT, 3::SMALLINT,
                    66::INTEGER, 1::INTEGER, 10::INTEGER, NULL, NULL,
                    NULL::BIGINT, 1::TINYINT, 1::TINYINT, 3::SMALLINT,
                    DATE '2013-12-31', DATE '2013-12-30', 1::SMALLINT, 1::SMALLINT,
                    1::SMALLINT, 501::INTEGER, 1::SMALLINT, 0::TINYINT, 0::INTEGER,
                    2::SMALLINT, 50::INTEGER, 102::INTEGER, 22::SMALLINT
                )
            ) AS rows(
                date_time, site_name, posa_continent, user_location_country,
                user_location_region, user_location_city,
                orig_destination_distance_key, orig_destination_distance, user_id,
                is_mobile, is_package, channel, srch_ci, srch_co, srch_adults_cnt,
                srch_children_cnt, srch_rm_cnt, srch_destination_id,
                srch_destination_type_id, is_booking, cnt, hotel_continent,
                hotel_country, hotel_market, hotel_cluster
            )
            """
        )
        con.execute(
            f"COPY train TO '{paths.train_path.as_posix()}' (FORMAT PARQUET)"
        )

        destination_columns = [
            "1::INTEGER AS srch_destination_id",
            *(f"{index / 1000.0}::REAL AS d{index}" for index in range(1, 150)),
        ]
        con.execute(
            "CREATE TABLE destinations AS SELECT " + ", ".join(destination_columns)
        )
        con.execute(
            f"COPY destinations TO '{paths.destinations_path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    return paths


def test_profile_sources_reports_semantic_risks(tmp_path: Path) -> None:
    paths = _write_synthetic_sources(tmp_path)

    profile = profile_sources(
        paths,
        threads=1,
        memory_limit="1GB",
        deep=True,
    )

    quality = profile["train"]["quality"]
    assert quality["total_rows"] == 3
    assert quality["booking_rows"] == 1
    assert quality["anonymous_rows"] == 1
    assert quality["nonpositive_cnt_rows"] == 1
    assert quality["negative_lead_time_rows"] == 1
    assert quality["nonpositive_stay_rows"] == 1

    context = profile["train"]["proxy_contexts"]
    assert context["proxy_contexts"] == 1
    assert context["eligible_interaction_rows"] == 2
    assert context["multicluster_contexts"] == 1
    assert context["multimarket_contexts"] == 1
    assert context["booking_bearing_contexts"] == 1

    assert (paths.artifacts_dir / "source_profile.json").exists()
    assert (paths.artifacts_dir / "source_profile.md").exists()
