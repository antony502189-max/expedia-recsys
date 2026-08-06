from pathlib import Path

import duckdb

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.source_reconciliation import reconcile_sources


def _write_sources(root: Path) -> AnalyticsPaths:
    paths = AnalyticsPaths.from_root(root)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.processed_dir.mkdir(parents=True, exist_ok=True)

    train_header = (
        "date_time,site_name,posa_continent,user_location_country,"
        "user_location_region,user_location_city,orig_destination_distance,user_id,"
        "is_mobile,is_package,channel,srch_ci,srch_co,srch_adults_cnt,"
        "srch_children_cnt,srch_rm_cnt,srch_destination_id,"
        "srch_destination_type_id,is_booking,cnt,hotel_continent,hotel_country,"
        "hotel_market,hotel_cluster\n"
    )
    train_rows = [
        "2014-01-01 10:00:00,2,3,66,1,10,100.0,1001,0,0,9,2014-02-01,"
        "2014-02-05,2,0,1,500,1,0,2,2,50,100,20\n",
        "bad-date,2,3,66,1,10,100.0,1002,0,0,9,2014-02-01,2014-02-05,"
        "2,0,1,500,1,0,2,2,50,100,20\n",
        "2014-01-03 10:00:00,2,3,66,1,10,100.0,1003,0,0,9,2014-02-01,"
        "2014-02-05,2,0,1,500,1,0,2,2,50,100,150\n",
    ]
    (paths.raw_dir / "train.csv").write_text(
        train_header + "".join(train_rows), encoding="utf-8"
    )

    destination_columns = ["srch_destination_id", *(f"d{i}" for i in range(1, 150))]
    valid_destination = ["500", *("0.1" for _ in range(149))]
    invalid_destination = ["", *("0.2" for _ in range(149))]
    (paths.raw_dir / "destinations.csv").write_text(
        ",".join(destination_columns)
        + "\n"
        + ",".join(valid_destination)
        + "\n"
        + ",".join(invalid_destination)
        + "\n",
        encoding="utf-8",
    )

    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
                SELECT
                    TRY_CAST(date_time AS TIMESTAMP) AS date_time,
                    TRY_CAST(site_name AS SMALLINT) AS site_name,
                    TRY_CAST(posa_continent AS SMALLINT) AS posa_continent,
                    TRY_CAST(user_location_country AS INTEGER) AS user_location_country,
                    TRY_CAST(user_location_region AS INTEGER) AS user_location_region,
                    TRY_CAST(user_location_city AS INTEGER) AS user_location_city,
                    NULLIF(orig_destination_distance, '') AS orig_destination_distance_key,
                    TRY_CAST(orig_destination_distance AS DOUBLE) AS orig_destination_distance,
                    TRY_CAST(user_id AS BIGINT) AS user_id,
                    TRY_CAST(is_mobile AS TINYINT) AS is_mobile,
                    TRY_CAST(is_package AS TINYINT) AS is_package,
                    TRY_CAST(channel AS SMALLINT) AS channel,
                    TRY_CAST(srch_ci AS DATE) AS srch_ci,
                    TRY_CAST(srch_co AS DATE) AS srch_co,
                    TRY_CAST(srch_adults_cnt AS SMALLINT) AS srch_adults_cnt,
                    TRY_CAST(srch_children_cnt AS SMALLINT) AS srch_children_cnt,
                    TRY_CAST(srch_rm_cnt AS SMALLINT) AS srch_rm_cnt,
                    TRY_CAST(srch_destination_id AS INTEGER) AS srch_destination_id,
                    TRY_CAST(srch_destination_type_id AS SMALLINT)
                        AS srch_destination_type_id,
                    TRY_CAST(is_booking AS TINYINT) AS is_booking,
                    TRY_CAST(cnt AS INTEGER) AS cnt,
                    TRY_CAST(hotel_continent AS SMALLINT) AS hotel_continent,
                    TRY_CAST(hotel_country AS INTEGER) AS hotel_country,
                    TRY_CAST(hotel_market AS INTEGER) AS hotel_market,
                    TRY_CAST(hotel_cluster AS SMALLINT) AS hotel_cluster
                FROM read_csv(
                    '{(paths.raw_dir / 'train.csv').as_posix()}',
                    header=true,
                    all_varchar=true,
                    nullstr=''
                )
                WHERE TRY_CAST(date_time AS TIMESTAMP) IS NOT NULL
                  AND TRY_CAST(hotel_cluster AS SMALLINT) BETWEEN 0 AND 99
            ) TO '{paths.train_path.as_posix()}' (FORMAT PARQUET)
            """
        )
        destination_select = [
            "TRY_CAST(srch_destination_id AS INTEGER) AS srch_destination_id",
            *(f"TRY_CAST(d{i} AS REAL) AS d{i}" for i in range(1, 150)),
        ]
        con.execute(
            f"""
            COPY (
                SELECT {', '.join(destination_select)}
                FROM read_csv(
                    '{(paths.raw_dir / 'destinations.csv').as_posix()}',
                    header=true,
                    all_varchar=true,
                    nullstr=''
                )
                WHERE TRY_CAST(srch_destination_id AS INTEGER) IS NOT NULL
            ) TO '{paths.destinations_path.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()
    return paths


def test_reconcile_sources_detects_prepare_rejections(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)

    report = reconcile_sources(paths, threads=1, memory_limit="1GB")

    train = report["train"]
    assert train["raw_rows"] == 3
    assert train["processed_rows"] == 1
    assert train["rows_rejected_by_recsys_prepare"] == 2
    assert train["prepare_filter_reconciles"] is True
    assert train["all_raw_rows_preserved_in_processed"] is False

    destinations = report["destinations"]
    assert destinations["raw_rows"] == 2
    assert destinations["processed_rows"] == 1
    assert destinations["rows_rejected_by_recsys_prepare"] == 1
    assert destinations["prepare_filter_reconciles"] is True

    assert (paths.artifacts_dir / "source_reconciliation.json").exists()
    assert (paths.artifacts_dir / "source_reconciliation.md").exists()
