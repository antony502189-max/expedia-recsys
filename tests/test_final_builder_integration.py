from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import DESTINATION_COLUMNS, TEST_COLUMNS, TRAIN_COLUMNS
from expedia_analytics.final_builder import build_final_analytics, compare_builds


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _train_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "date_time": "2014-01-02 10:00:00",
        "site_name": 2,
        "posa_continent": 3,
        "user_location_country": 66,
        "user_location_region": 174,
        "user_location_city": 24103,
        "orig_destination_distance": 100.5,
        "user_id": 10,
        "is_mobile": 0,
        "is_package": 0,
        "channel": 9,
        "srch_ci": "2014-01-10",
        "srch_co": "2014-01-12",
        "srch_adults_cnt": 2,
        "srch_children_cnt": 0,
        "srch_rm_cnt": 1,
        "srch_destination_id": 1000,
        "srch_destination_type_id": 1,
        "is_booking": 0,
        "cnt": 1,
        "hotel_continent": 2,
        "hotel_country": 50,
        "hotel_market": 500,
        "hotel_cluster": 12,
    }
    row.update(overrides)
    return row


def _test_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 0,
        "date_time": "2015-01-02 10:00:00",
        "site_name": 2,
        "posa_continent": 3,
        "user_location_country": 66,
        "user_location_region": 174,
        "user_location_city": 24103,
        "orig_destination_distance": 120.0,
        "user_id": 10,
        "is_mobile": 0,
        "is_package": 0,
        "channel": 9,
        "srch_ci": "2015-01-10",
        "srch_co": "2015-01-12",
        "srch_adults_cnt": 2,
        "srch_children_cnt": 0,
        "srch_rm_cnt": 1,
        "srch_destination_id": 1000,
        "srch_destination_type_id": 1,
        "hotel_continent": 2,
        "hotel_country": 50,
        "hotel_market": 500,
    }
    row.update(overrides)
    return row


def _prepare_project(root: Path) -> AnalyticsPaths:
    paths = AnalyticsPaths.from_root(root)
    contract_source = Path(__file__).resolve().parents[1] / "config" / "analytics_contract.json"
    paths.contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract = json.loads(contract_source.read_text(encoding="utf-8"))
    contract["quality_thresholds"]["maximum_quarantine_rate"] = 0.5
    contract["quality_thresholds"]["maximum_proxy_multimarket_rate"] = 1.0
    paths.contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    train = [
        _train_row(),
        _train_row(hotel_cluster=13, hotel_market=501),
        _train_row(
            date_time="2014-01-02 11:00:00",
            is_booking=1,
            hotel_cluster=13,
            hotel_market=501,
        ),
        _train_row(
            date_time="2014-02-02 09:00:00",
            user_id=11,
            is_mobile=1,
            is_package=1,
            srch_children_cnt=1,
            is_booking=1,
            srch_destination_id=1001,
            hotel_market=502,
        ),
        _train_row(
            date_time="2014-12-23 21:28:17",
            user_id=13,
            srch_ci="2558-03-15",
            srch_co="2558-03-16",
        ),
        _train_row(date_time="not-a-date", user_id=12),
    ]
    _write_csv(paths.raw_dir / "train.csv", [item.name for item in TRAIN_COLUMNS], train)

    test = [_test_row(), _test_row(id=1, is_mobile=1, hotel_market=502)]
    _write_csv(paths.raw_dir / "test.csv", [item.name for item in TEST_COLUMNS], test)

    destination_rows = []
    for destination_id in (1000, 1001):
        destination_rows.append(
            {
                "srch_destination_id": destination_id,
                **{f"d{index}": index / 1000 for index in range(1, 150)},
            }
        )
    _write_csv(
        paths.raw_dir / "destinations.csv",
        [item.name for item in DESTINATION_COLUMNS],
        destination_rows,
    )
    return paths


def test_final_build_reconciles_and_is_reproducible(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    first = build_final_analytics(
        paths,
        threads=1,
        memory_limit="1GB",
        build_id="synthetic-a",
    )
    second = build_final_analytics(
        paths,
        threads=1,
        memory_limit="1GB",
        build_id="synthetic-b",
    )
    assert first["quality"]["passed"]
    assert second["quality"]["passed"]

    database = paths.analytics_dir / "synthetic-a" / "expedia_analytics.duckdb"
    connection = duckdb.connect(str(database), read_only=True)
    try:
        anomaly = connection.execute(
            """
            SELECT trip_date_quality, is_plausible_lead_time, lead_time_segment
            FROM analytics.fct_hotel_interactions
            WHERE checkin_date = DATE '2558-03-15'
            """
        ).fetchone()
        assert anomaly == ("lead_time_out_of_scope", False, "out_of_scope_gt_730")

        maximum_date, calendar_days = connection.execute(
            "SELECT MAX(date_day), COUNT(*) FROM analytics.dim_date"
        ).fetchone()
        assert maximum_date.year == 2014
        assert calendar_days < 1000

        quality_rows = connection.execute(
            """
            SELECT affected_rows
            FROM analytics.dm_data_quality_summary
            WHERE quality_rule = 'trip_date_quality:lead_time_out_of_scope'
            """
        ).fetchone()
        assert quality_rows == (1,)

        seasonality_rows = connection.execute(
            "SELECT SUM(interaction_rows) FROM analytics.dm_checkin_seasonality"
        ).fetchone()[0]
        assert seasonality_rows == 4
    finally:
        connection.close()

    comparison = compare_builds(paths, "synthetic-a", "synthetic-b", exact=True)
    assert comparison["identical_logical_checksums"]
    assert comparison["exact_identical"]

    pointer = json.loads(paths.latest_pointer_path.read_text(encoding="utf-8"))
    assert pointer["build_id"] == "synthetic-b"
    assert Path(pointer["database"]).exists()
