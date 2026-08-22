# ruff: noqa: E501
"""Validate the Stage 2 canonical dashboard BI layer without touching Stage 1."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb

from expedia_analytics.bi_dashboard import BI_CONTRACT_VERSION, MART_SPECS, SOURCE_BUILD_ID

REQUIRED_COLUMNS = {
    "bi_overview_monthly": {
        "event_month",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "active_users",
        "is_partial_month",
    },
    "bi_segments_monthly": {
        "event_month",
        "segment_type",
        "segment_value",
        "segment_sort_order",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "support_level",
        "is_valid_segment",
    },
    "bi_booking_window": {
        "lead_time_segment",
        "lead_time_sort_order",
        "stay_segment",
        "stay_sort_order",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "booking_interaction_share_ci_low",
        "booking_interaction_share_ci_high",
        "support_level",
    },
    "bi_traveller_planning_monthly": {
        "event_month",
        "traveller_segment",
        "traveller_sort_order",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "avg_valid_lead_days",
        "avg_valid_stay_nights",
        "support_level",
    },
    "bi_checkin_seasonality": {
        "checkin_month",
        "checkin_year",
        "checkin_month_number",
        "checkin_month_name",
        "traveller_segment",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
    },
    "bi_destination_performance": {
        "destination_id",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "entity_users",
        "support_level",
        "overall_booking_interaction_share",
        "interaction_volume_q3_strong",
        "investigation_class",
        "investigation_candidate",
    },
    "bi_hotel_market_performance": {
        "hotel_market",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "entity_users",
        "support_level",
        "overall_booking_interaction_share",
        "investigation_class",
        "investigation_candidate",
    },
    "bi_destination_monthly": {
        "event_month",
        "destination_id",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "entity_users",
        "support_level",
    },
    "bi_routes": {
        "origin_id",
        "destination_id",
        "interaction_rows",
        "booking_rows",
        "booking_interaction_share",
        "entity_users",
        "support_level",
    },
    "bi_observed_recurrence": {
        "cohort_month",
        "activity_month",
        "observed_age_month",
        "cohort_users",
        "observed_active_users",
        "booking_users",
        "observed_recurrence_share",
        "is_censored",
        "observable_horizon_months",
    },
    "bi_acceptance_status": {
        "accepted",
        "failures",
        "exact_objects_verified",
        "exact_objects_total",
        "stage1_build_id",
    },
    "bi_missingness_daily": {
        "event_date",
        "field_name",
        "eligible_rows",
        "missing_rows",
        "missing_share",
    },
    "bi_proxy_ambiguity": {
        "ambiguity_type",
        "affected_contexts",
        "proxy_contexts",
        "affected_share",
    },
    "bi_booking_population_drift_summary": {
        "dimension_name",
        "total_variation_distance",
        "population_stability_index",
        "category_count",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _scalar(con: duckdb.DuckDBPyConnection, query: str) -> Any:
    return con.execute(query).fetchone()[0]


def validate_bi_layer(root: Path, *, build_id: str = SOURCE_BUILD_ID) -> dict[str, Any]:
    root = root.resolve()
    bi_dir = root / "data" / "bi" / build_id
    source_database = root / "data" / "analytics" / build_id / "expedia_analytics.duckdb"
    checks: list[dict[str, Any]] = []
    manifest_path = bi_dir / "manifest.json"
    _check(checks, "manifest_exists", manifest_path.exists(), str(manifest_path))
    if not manifest_path.exists() or not source_database.exists():
        return {"passed": False, "checks": checks, "failure_count": 1}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _check(
        checks,
        "canonical_contract_version",
        manifest.get("bi_contract_version") == BI_CONTRACT_VERSION,
        manifest.get("bi_contract_version"),
    )
    _check(
        checks,
        "source_build_id",
        manifest.get("source_build_id") == build_id,
        manifest.get("source_build_id"),
    )
    manifest_marts = {item["name"]: item for item in manifest.get("marts", [])}
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{_quote(source_database)}' AS source (READ_ONLY)")
        for name, spec in MART_SPECS.items():
            path = bi_dir / f"{name}.parquet"
            _check(checks, f"{name}.exists", path.exists(), str(path))
            if not path.exists():
                continue
            relation = f"read_parquet('{_quote(path)}')"
            described = {
                row[0]: row[1]
                for row in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
            }
            missing = sorted(REQUIRED_COLUMNS[name] - set(described))
            _check(checks, f"{name}.canonical_columns", not missing, {"missing": missing})
            non_string_types = [column for column, data_type in described.items() if not data_type]
            _check(checks, f"{name}.valid_types", not non_string_types, non_string_types)
            grain = ", ".join(spec["grain"])
            rows, distinct_rows = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT ({grain})) FROM {relation}"
            ).fetchone()
            _check(
                checks,
                f"{name}.unique_grain",
                rows == distinct_rows,
                {"rows": rows, "distinct": distinct_rows},
            )
            key_nulls = _scalar(
                con,
                f"SELECT COUNT(*) FROM {relation} WHERE "
                + " OR ".join(f"{column} IS NULL" for column in spec["grain"]),
            )
            _check(checks, f"{name}.non_null_grain", key_nulls == 0, key_nulls)
            manifest_mart = manifest_marts.get(name, {})
            _check(
                checks,
                f"{name}.manifest_row_count",
                manifest_mart.get("row_count") == rows,
                {"actual": rows, "manifest": manifest_mart.get("row_count")},
            )
            _check(
                checks, f"{name}.checksum", manifest_mart.get("checksum") == _sha256(path), "sha256"
            )

        for name in (
            "bi_overview_monthly",
            "bi_segments_monthly",
            "bi_booking_window",
            "bi_traveller_planning_monthly",
            "bi_checkin_seasonality",
            "bi_destination_performance",
            "bi_hotel_market_performance",
            "bi_destination_monthly",
            "bi_routes",
        ):
            relation = f"read_parquet('{_quote(bi_dir / (name + '.parquet'))}')"
            invalid = _scalar(
                con,
                f"SELECT COUNT(*) FROM {relation} WHERE booking_rows < 0 OR interaction_rows < 0 OR booking_rows > interaction_rows OR booking_interaction_share NOT BETWEEN 0 AND 1",
            )
            _check(checks, f"{name}.outcome_bounds", invalid == 0, invalid)
        for name in (
            "bi_segments_monthly",
            "bi_booking_window",
            "bi_traveller_planning_monthly",
            "bi_destination_performance",
            "bi_hotel_market_performance",
            "bi_destination_monthly",
            "bi_routes",
        ):
            relation = f"read_parquet('{_quote(bi_dir / (name + '.parquet'))}')"
            invalid = _scalar(
                con,
                f"SELECT COUNT(*) FROM {relation} WHERE support_level != CASE WHEN interaction_rows < 100 THEN 'low' WHEN interaction_rows < 1000 THEN 'adequate' ELSE 'strong' END",
            )
            _check(checks, f"{name}.support_thresholds", invalid == 0, invalid)

        overview = f"read_parquet('{_quote(bi_dir / 'bi_overview_monthly.parquet')}')"
        interactions, bookings, share = con.execute(
            f"SELECT SUM(interaction_rows), SUM(booking_rows), SUM(booking_rows)::DOUBLE / SUM(interaction_rows) FROM {overview}"
        ).fetchone()
        _check(checks, "headline_interactions", interactions == 37670293, interactions)
        _check(checks, "headline_bookings", bookings == 3000693, bookings)
        _check(checks, "headline_booking_share", abs(share - 0.079656747) < 1e-8, share)
        _check(
            checks,
            "january_2013_partial",
            _scalar(
                con,
                f"SELECT is_partial_month FROM {overview} WHERE event_month = DATE '2013-01-01'",
            )
            is True,
            "2013-01-01",
        )
        _check(
            checks,
            "december_2014_active_users",
            _scalar(
                con, f"SELECT active_users FROM {overview} WHERE event_month = DATE '2014-12-01'"
            )
            == 353387,
            353387,
        )
        _check(
            checks,
            "overview_event_month_range",
            tuple(
                str(value)
                for value in con.execute(
                    f"SELECT MIN(event_month), MAX(event_month) FROM {overview}"
                ).fetchone()
            )
            == ("2013-01-01", "2014-12-01"),
            "2013-01 through 2014-12",
        )

        segments = f"read_parquet('{_quote(bi_dir / 'bi_segments_monthly.parquet')}')"
        for device, expected_interactions, expected_bookings in (
            ("mobile", 5082721, 297707),
            ("desktop", 32587572, 2702986),
        ):
            actual = con.execute(
                f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {segments} WHERE segment_type = 'device' AND segment_value = '{device}'"
            ).fetchone()
            _check(
                checks,
                f"device_{device}_anchor",
                actual == (expected_interactions, expected_bookings),
                actual,
            )

        booking_window = f"read_parquet('{_quote(bi_dir / 'bi_booking_window.parquet')}')"
        _check(
            checks,
            "booking_window_valid_cells",
            _scalar(con, f"SELECT COUNT(*) FROM {booking_window}") == 30,
            30,
        )
        for lead, stay, expected in (
            ("same_day", "01_night", (759768, 145488)),
            ("181_730_days", "15_365_nights", (36710, 505)),
        ):
            actual = con.execute(
                f"SELECT interaction_rows, booking_rows FROM {booking_window} WHERE lead_time_segment = '{lead}' AND stay_segment = '{stay}'"
            ).fetchone()
            _check(checks, f"booking_window_{lead}_{stay}", actual == expected, actual)

        destination = f"read_parquet('{_quote(bi_dir / 'bi_destination_performance.parquet')}')"
        _check(
            checks,
            "strong_destinations",
            _scalar(con, f"SELECT COUNT(*) FROM {destination} WHERE support_level = 'strong'")
            == 2970,
            2970,
        )
        for destination_id, expected in ((8791, (619520, 18342)), (11439, (367301, 9397))):
            actual = con.execute(
                f"SELECT interaction_rows, booking_rows FROM {destination} WHERE destination_id = {destination_id}"
            ).fetchone()
            _check(checks, f"destination_{destination_id}", actual == expected, actual)
        hotel_market = f"read_parquet('{_quote(bi_dir / 'bi_hotel_market_performance.parquet')}')"
        _check(
            checks,
            "strong_hotel_markets",
            _scalar(con, f"SELECT COUNT(*) FROM {hotel_market} WHERE support_level = 'strong'")
            == 1526,
            1526,
        )
        checkin = f"read_parquet('{_quote(bi_dir / 'bi_checkin_seasonality.parquet')}')"
        _check(
            checks,
            "checkin_time_is_separate_and_extends_beyond_events",
            con.execute(f"SELECT MAX(checkin_month) FROM {checkin}").fetchone()[0]
            > con.execute(f"SELECT MAX(event_month) FROM {overview}").fetchone()[0],
            "checkin_month extends beyond observed event_month",
        )

        recurrence = f"read_parquet('{_quote(bi_dir / 'bi_observed_recurrence.parquet')}')"
        cohort_total = _scalar(
            con, f"SELECT SUM(cohort_users) FROM {recurrence} WHERE observed_age_month = 0"
        )
        _check(checks, "recurrence_age_zero_users", cohort_total == 1198786, cohort_total)
        censored, null_shares, populated_censored = con.execute(
            f"SELECT COUNT(*) FILTER (WHERE is_censored), COUNT(*) FILTER (WHERE is_censored AND observed_recurrence_share IS NULL), COUNT(*) FILTER (WHERE is_censored AND (observed_active_users IS NOT NULL OR booking_users IS NOT NULL)) FROM {recurrence}"
        ).fetchone()
        _check(
            checks,
            "recurrence_censoring",
            censored == 276 and null_shares == censored and populated_censored == 0,
            {"censored": censored, "null_shares": null_shares, "populated": populated_censored},
        )

        missingness = f"read_parquet('{_quote(bi_dir / 'bi_missingness_daily.parquet')}')"
        invalid_missingness = _scalar(
            con,
            f"SELECT COUNT(*) FROM {missingness} WHERE missing_rows < 0 OR eligible_rows < missing_rows OR missing_share NOT BETWEEN 0 AND 1",
        )
        _check(checks, "missingness_bounds", invalid_missingness == 0, invalid_missingness)
        proxy = f"read_parquet('{_quote(bi_dir / 'bi_proxy_ambiguity.parquet')}')"
        invalid_proxy = _scalar(
            con,
            f"SELECT COUNT(*) FROM {proxy} WHERE affected_contexts < 0 OR proxy_contexts < affected_contexts OR affected_share NOT BETWEEN 0 AND 1",
        )
        _check(checks, "proxy_ambiguity_bounds", invalid_proxy == 0, invalid_proxy)

        acceptance = f"read_parquet('{_quote(bi_dir / 'bi_acceptance_status.parquet')}')"
        accepted = con.execute(
            f"SELECT accepted, failures, exact_objects_verified, exact_objects_total, stage1_build_id FROM {acceptance}"
        ).fetchone()
        _check(checks, "stage1_acceptance", accepted == (True, 0, 43, 43, build_id), accepted)

        reconciliations = [
            (
                "overview_interactions",
                "SELECT SUM(logged_interaction_rows) FROM source.analytics.dm_sample_activity_monthly",
                f"SELECT SUM(interaction_rows) FROM {overview}",
            ),
            (
                "overview_bookings",
                "SELECT SUM(booking_rows) FROM source.analytics.dm_interaction_outcome_monthly",
                f"SELECT SUM(booking_rows) FROM {overview}",
            ),
            (
                "segments",
                "SELECT SUM(interaction_rows), SUM(booking_rows) FROM source.analytics.dm_segment_monthly",
                f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {segments}",
            ),
            (
                "booking_window",
                "SELECT SUM(interaction_rows), SUM(booking_rows) FROM source.analytics.dm_booking_window",
                f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {booking_window}",
            ),
            (
                "traveller_planning",
                "SELECT SUM(interaction_rows), SUM(booking_rows) "
                "FROM source.analytics.dm_travel_patterns",
                "SELECT SUM(interaction_rows), SUM(booking_rows) "
                "FROM read_parquet('"
                + _quote(bi_dir / "bi_traveller_planning_monthly.parquet")
                + "')",
            ),
            (
                "checkin_seasonality",
                "SELECT SUM(interaction_rows), SUM(booking_rows) "
                "FROM source.analytics.dm_checkin_seasonality",
                f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {checkin}",
            ),
            (
                "destination",
                "SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM source.analytics.dm_destination_performance",
                f"SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM {destination}",
            ),
            (
                "hotel_market",
                "SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM source.analytics.dm_hotel_market_performance",
                f"SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM {hotel_market}",
            ),
            (
                "destination_monthly",
                "SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) "
                "FROM source.analytics.dm_destination_monthly",
                "SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) "
                "FROM read_parquet('"
                + _quote(bi_dir / "bi_destination_monthly.parquet")
                + "')",
            ),
            (
                "routes",
                "SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM source.analytics.dm_origin_destination_routes",
                f"SELECT SUM(interaction_rows), SUM(booking_rows), COUNT(*) FROM read_parquet('{_quote(bi_dir / 'bi_routes.parquet')}')",
            ),
            (
                "recurrence",
                "SELECT SUM(cohort_users), SUM(observed_active_users), COUNT(*) "
                "FROM source.analytics.dm_observed_recurrence",
                f"SELECT SUM(cohort_users), SUM(observed_active_users), COUNT(*) FROM {recurrence}",
            ),
            (
                "missingness",
                "SELECT SUM(eligible_rows), SUM(missing_rows), COUNT(*) "
                "FROM source.analytics.dm_missingness_daily",
                f"SELECT SUM(eligible_rows), SUM(missing_rows), COUNT(*) FROM {missingness}",
            ),
            (
                "proxy_ambiguity",
                "SELECT SUM(affected_contexts), SUM(proxy_contexts), COUNT(*) "
                "FROM source.analytics.dm_proxy_context_ambiguity",
                f"SELECT SUM(affected_contexts), SUM(proxy_contexts), COUNT(*) FROM {proxy}",
            ),
        ]
        for name, source_query, bi_query in reconciliations:
            source_values = con.execute(source_query).fetchone()
            bi_values = con.execute(bi_query).fetchone()
            _check(
                checks,
                f"source_reconciliation_{name}",
                source_values == bi_values,
                {"source": source_values, "bi": bi_values},
            )
    finally:
        con.close()
    failures = [item for item in checks if not item["passed"]]
    return {"passed": not failures, "checks": checks, "failure_count": len(failures)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-id", default=SOURCE_BUILD_ID)
    args = parser.parse_args()
    report = validate_bi_layer(args.root, build_id=args.build_id)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
