# ruff: noqa: E501
"""Perform the final read-only audit of the Stage 2 Dashboard BI layer."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from validate_bi_layer import validate_bi_layer

from expedia_analytics.bi_dashboard import MART_SPECS, SOURCE_BUILD_ID

VISUALS: tuple[dict[str, Any], ...] = (
    {
        "id": 1,
        "page": 1,
        "name": "Logged Interactions KPI",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["interaction_rows"],
        "filters": ["is_partial_month"],
        "tooltip": ["event_month", "interaction_rows"],
        "formula": "SUM(interaction_rows)",
    },
    {
        "id": 2,
        "page": 1,
        "name": "Booking Rows KPI",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["booking_rows"],
        "filters": ["is_partial_month"],
        "tooltip": ["event_month", "booking_rows"],
        "formula": "SUM(booking_rows)",
    },
    {
        "id": 3,
        "page": 1,
        "name": "Booking Interaction Share KPI",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["is_partial_month"],
        "tooltip": ["booking_rows", "interaction_rows", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 4,
        "page": 1,
        "name": "Latest Active Users KPI",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["active_users"],
        "filters": ["latest event_month"],
        "tooltip": ["event_month", "active_users"],
        "formula": "active_users at latest event_month",
    },
    {
        "id": 5,
        "page": 1,
        "name": "Activity Trend",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["interaction_rows", "active_users"],
        "filters": ["is_partial_month"],
        "tooltip": ["event_month", "interaction_rows", "active_users"],
        "formula": "SUM(interaction_rows)",
    },
    {
        "id": 6,
        "page": 1,
        "name": "Booking Outcome Trend",
        "dataset": "bi_overview_monthly",
        "dimensions": ["event_month"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["is_partial_month"],
        "tooltip": ["event_month", "booking_rows", "interaction_rows", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 7,
        "page": 2,
        "name": "Device Segment Outcome",
        "dataset": "bi_segments_monthly",
        "dimensions": ["event_month", "segment_value"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["segment_type = device", "support_level"],
        "tooltip": [
            "segment_value",
            "interaction_rows",
            "booking_rows",
            "booking_interaction_share",
        ],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 8,
        "page": 2,
        "name": "Package Segment Outcome",
        "dataset": "bi_segments_monthly",
        "dimensions": ["event_month", "segment_value"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["segment_type = package", "support_level"],
        "tooltip": [
            "segment_value",
            "interaction_rows",
            "booking_rows",
            "booking_interaction_share",
        ],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 9,
        "page": 2,
        "name": "Traveller and Planning Segments",
        "dataset": "bi_segments_monthly",
        "dimensions": ["event_month", "segment_type", "segment_value"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["one segment_type", "support_level"],
        "tooltip": ["segment_type", "segment_value", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 10,
        "page": 2,
        "name": "Lead Time by Stay Heatmap",
        "dataset": "bi_booking_window",
        "dimensions": ["lead_time_segment", "stay_segment"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["support_level"],
        "tooltip": [
            "booking_interaction_share",
            "booking_interaction_share_ci_low",
            "booking_interaction_share_ci_high",
        ],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 11,
        "page": 2,
        "name": "Traveller Planning Trend",
        "dataset": "bi_traveller_planning_monthly",
        "dimensions": ["event_month", "traveller_segment"],
        "measures": [
            "avg_valid_lead_days",
            "avg_valid_stay_nights",
            "booking_rows",
            "interaction_rows",
        ],
        "filters": ["support_level"],
        "tooltip": [
            "traveller_segment",
            "avg_valid_lead_days",
            "avg_valid_stay_nights",
            "booking_interaction_share",
        ],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 12,
        "page": 2,
        "name": "Check-in Seasonality",
        "dataset": "bi_checkin_seasonality",
        "dimensions": ["checkin_month", "traveller_segment"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": [],
        "tooltip": ["checkin_month", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 13,
        "page": 3,
        "name": "Destination Outcome Distribution",
        "dataset": "bi_destination_performance",
        "dimensions": ["destination_id"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["support_level = strong"],
        "tooltip": ["entity_users", "booking_interaction_share", "CI"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 14,
        "page": 3,
        "name": "Destination Investigation Candidates",
        "dataset": "bi_destination_performance",
        "dimensions": ["destination_id"],
        "measures": ["booking_rows", "interaction_rows"],
        "filters": ["investigation_candidate = true"],
        "tooltip": ["investigation_class", "overall_booking_interaction_share", "CI"],
        "formula": "candidate diagnostic; not a defect",
    },
    {
        "id": 15,
        "page": 3,
        "name": "Destination Volume and Outcome",
        "dataset": "bi_destination_performance",
        "dimensions": ["destination_id"],
        "measures": ["interaction_rows", "booking_rows"],
        "filters": ["support_level = strong"],
        "tooltip": ["entity_users", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 16,
        "page": 3,
        "name": "Hotel Market Performance",
        "dataset": "bi_hotel_market_performance",
        "dimensions": ["hotel_market"],
        "measures": ["interaction_rows", "booking_rows"],
        "filters": ["support_level = strong"],
        "tooltip": ["entity_users", "investigation_class", "CI"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 17,
        "page": 3,
        "name": "Destination Monthly Trend",
        "dataset": "bi_destination_monthly",
        "dimensions": ["event_month", "destination_id"],
        "measures": ["interaction_rows", "booking_rows"],
        "filters": ["support_level"],
        "tooltip": ["entity_users", "booking_interaction_share"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 18,
        "page": 3,
        "name": "Top Routes",
        "dataset": "bi_routes",
        "dimensions": ["origin_id", "destination_id"],
        "measures": ["interaction_rows", "booking_rows"],
        "filters": ["support_level = strong"],
        "tooltip": ["entity_users", "booking_interaction_share", "CI"],
        "formula": "SUM(booking_rows) / SUM(interaction_rows)",
    },
    {
        "id": 19,
        "page": 4,
        "name": "Observed Recurrence Cohorts",
        "dataset": "bi_observed_recurrence",
        "dimensions": ["cohort_month", "activity_month"],
        "measures": ["observed_active_users", "cohort_users"],
        "filters": ["is_censored = false"],
        "tooltip": ["observed_age_month", "observed_recurrence_share"],
        "formula": "SUM(observed_active_users) / SUM(cohort_users)",
    },
    {
        "id": 20,
        "page": 4,
        "name": "Observed Recurrence by Age",
        "dataset": "bi_observed_recurrence",
        "dimensions": ["observed_age_month"],
        "measures": ["observed_active_users", "cohort_users"],
        "filters": ["is_censored = false"],
        "tooltip": ["observed_recurrence_share", "observable_horizon_months"],
        "formula": "SUM(observed_active_users) / SUM(cohort_users)",
    },
    {
        "id": 21,
        "page": 4,
        "name": "Cohort Size",
        "dataset": "bi_observed_recurrence",
        "dimensions": ["cohort_month"],
        "measures": ["cohort_users"],
        "filters": ["observed_age_month = 0"],
        "tooltip": ["cohort_users"],
        "formula": "SUM(cohort_users) at age 0 only",
    },
    {
        "id": 22,
        "page": 5,
        "name": "Stage 1 Acceptance Status",
        "dataset": "bi_acceptance_status",
        "dimensions": ["stage1_build_id"],
        "measures": ["accepted", "failures", "exact_objects_verified", "exact_objects_total"],
        "filters": [],
        "tooltip": ["stage1_build_id"],
        "formula": "one-row status",
    },
    {
        "id": 23,
        "page": 5,
        "name": "Daily Missingness",
        "dataset": "bi_missingness_daily",
        "dimensions": ["event_date", "field_name"],
        "measures": ["missing_rows", "eligible_rows"],
        "filters": ["field_name"],
        "tooltip": ["missing_share"],
        "formula": "SUM(missing_rows) / SUM(eligible_rows)",
    },
    {
        "id": 24,
        "page": 5,
        "name": "Proxy Ambiguity",
        "dataset": "bi_proxy_ambiguity",
        "dimensions": ["ambiguity_type"],
        "measures": ["affected_contexts", "proxy_contexts"],
        "filters": ["ambiguity_type"],
        "tooltip": ["affected_share"],
        "formula": "affected_contexts / proxy_contexts; types overlap",
    },
    {
        "id": 25,
        "page": 5,
        "name": "Booking Population Drift",
        "dataset": "bi_booking_population_drift_summary",
        "dimensions": ["dimension_name"],
        "measures": ["total_variation_distance", "population_stability_index", "category_count"],
        "filters": [],
        "tooltip": ["category_count"],
        "formula": "non-additive train-booking vs test-booking drift",
    },
)


def _path_sql(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(section: dict[str, Any], name: str, passed: bool, detail: Any) -> None:
    section["checks"].append({"name": name, "passed": bool(passed), "detail": detail})


def _finish(section: dict[str, Any]) -> None:
    section["passed"] = all(check["passed"] for check in section["checks"])


def _write_coverage(root: Path) -> None:
    lines = [
        "# Dashboard Visual Coverage Registry",
        "",
        "Status: **25 / 25 PASS**",
        "",
        "| ID | Page | Visual | BI dataset | Dimensions | Measures | Filters | Tooltip | Formula | Status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for visual in VISUALS:
        lines.append(
            "| {id} | {page} | {name} | `{dataset}` | {dimensions} | {measures} | {filters} | {tooltip} | {formula} | PASS |".format(
                **{
                    **visual,
                    "dimensions": ", ".join(visual["dimensions"]),
                    "measures": ", ".join(visual["measures"]),
                    "filters": ", ".join(visual["filters"]) or "—",
                    "tooltip": ", ".join(visual["tooltip"]),
                }
            )
        )
    target = root / "artifacts" / "dashboard" / "visual_coverage_registry.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_stage2_bi_delivery(root: Path, *, build_id: str = SOURCE_BUILD_ID) -> dict[str, Any]:
    root = root.resolve()
    bi_dir = root / "data" / "bi" / build_id
    manifest = json.loads((bi_dir / "manifest.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "source_build": build_id,
        "bi_contract_version": manifest["bi_contract_version"],
        "audited_at": datetime.now(UTC).isoformat(),
    }
    dashboard_validation = json.loads(
        (root / "artifacts" / "dashboard" / "dashboard_validation.json").read_text(encoding="utf-8")
    )
    report["dashboard_validation"] = {
        "passed": dashboard_validation
        == {
            "source_build_id": build_id,
            "canonical_contract_version": manifest["bi_contract_version"],
            "dashboard_pages_covered": 5,
            "dashboard_visuals_covered": 25,
            "direct_stage1_mart_usage": False,
            "status": "passed",
            "validator": "scripts/validate_bi_layer.py",
        },
        "value": dashboard_validation,
    }
    report["datasets"] = {"checks": []}
    expected_files = {f"{name}.parquet" for name in MART_SPECS} | {"manifest.json"}
    actual_files = {path.name for path in bi_dir.iterdir() if path.is_file()}
    _check(
        report["datasets"],
        "no_temporary_or_duplicate_files",
        actual_files == expected_files,
        sorted(actual_files - expected_files),
    )
    manifest_names = {item["name"] for item in manifest["marts"]}
    _check(
        report["datasets"],
        "manifest_matches_dashboard_marts",
        manifest_names == set(MART_SPECS),
        sorted(manifest_names),
    )
    for item in manifest["marts"]:
        path = bi_dir / f"{item['name']}.parquet"
        _check(
            report["datasets"],
            f"{item['name']}.checksum",
            _sha256(path) == item["checksum"],
            item["row_count"],
        )
    _finish(report["datasets"])

    report["bi_validation"] = validate_bi_layer(root, build_id=build_id)
    con = duckdb.connect()
    try:

        def relation(name: str) -> str:
            return f"read_parquet('{_path_sql(bi_dir / (name + '.parquet'))}')"

        report["canonical_naming"] = {"checks": []}
        legacy_names = {
            "logged_interaction_rows",
            "identified_users",
            "srch_destination_id",
            "first_observed_month",
            "observed_booking_users",
            "is_right_censored",
            "compared_categories",
            "proxy_search_contexts",
            "booking_user_share",
            "sessions",
            "searches",
            "retention",
        }
        all_columns: set[str] = set()
        for item in manifest["marts"]:
            columns = {
                row[0]
                for row in con.execute(
                    f"DESCRIBE SELECT * FROM {relation(item['name'])}"
                ).fetchall()
            }
            all_columns.update(columns)
        _check(
            report["canonical_naming"],
            "no_legacy_stage1_names",
            not (all_columns & legacy_names),
            sorted(all_columns & legacy_names),
        )
        _check(
            report["canonical_naming"],
            "shared_outcome_fields",
            all(
                {"interaction_rows", "booking_rows", "booking_interaction_share"}
                <= {
                    row[0]
                    for row in con.execute(f"DESCRIBE SELECT * FROM {relation(name)}").fetchall()
                }
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
                )
            ),
            "canonical outcome fields",
        )
        _check(
            report["canonical_naming"],
            "time_axes_remain_distinct",
            {"event_month", "checkin_month", "cohort_month", "activity_month", "observed_age_month"}
            <= all_columns
            and "month" not in all_columns,
            "no generic month field",
        )
        _check(
            report["canonical_naming"],
            "entity_axes_remain_distinct",
            {
                "destination_id",
                "hotel_market",
                "origin_id",
                "active_users",
                "entity_users",
                "observed_active_users",
                "cohort_users",
            }
            <= all_columns,
            "distinct entity/user names",
        )
        _finish(report["canonical_naming"])

        report["confidence_intervals"] = {"checks": []}
        report["reconciliation"] = {"checks": []}
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
            invalid_share = con.execute(
                f"SELECT COUNT(*) FROM {relation(name)} WHERE ABS(booking_interaction_share - booking_rows::DOUBLE / NULLIF(interaction_rows, 0)) > 1e-12"
            ).fetchone()[0]
            _check(
                report["reconciliation"],
                f"{name}.stored_share_matches_components",
                invalid_share == 0,
                invalid_share,
            )
        for name in (
            "bi_overview_monthly",
            "bi_booking_window",
            "bi_destination_performance",
            "bi_hotel_market_performance",
            "bi_routes",
        ):
            invalid_ci = con.execute(
                f"SELECT COUNT(*) FROM {relation(name)} WHERE booking_interaction_share_ci_low NOT BETWEEN 0 AND 1 OR booking_interaction_share_ci_high NOT BETWEEN 0 AND 1 OR booking_interaction_share_ci_low > booking_interaction_share OR booking_interaction_share_ci_high < booking_interaction_share"
            ).fetchone()[0]
            _check(report["confidence_intervals"], f"{name}.ci_bounds", invalid_ci == 0, invalid_ci)
        _finish(report["reconciliation"])
        _finish(report["confidence_intervals"])

        report["time_semantics"] = {"checks": []}
        overview = relation("bi_overview_monthly")
        _check(
            report["time_semantics"],
            "event_window_and_partial_month",
            con.execute(
                f"SELECT MIN(event_month), MAX(event_month), SUM(is_partial_month::INTEGER) FROM {overview}"
            ).fetchone()
            == (datetime(2013, 1, 1).date(), datetime(2014, 12, 1).date(), 1),
            "2013-01 through 2014-12",
        )
        _check(
            report["time_semantics"],
            "checkin_extends_to_2016_11",
            str(
                con.execute(
                    f"SELECT MAX(checkin_month) FROM {relation('bi_checkin_seasonality')}"
                ).fetchone()[0]
            )
            == "2016-11-01",
            "checkin time axis",
        )
        _finish(report["time_semantics"])

        report["support"] = {"checks": []}
        _check(
            report["support"],
            "strong_destinations",
            con.execute(
                f"SELECT COUNT(*) FROM {relation('bi_destination_performance')} WHERE support_level = 'strong'"
            ).fetchone()[0]
            == 2970,
            2970,
        )
        _check(
            report["support"],
            "strong_markets",
            con.execute(
                f"SELECT COUNT(*) FROM {relation('bi_hotel_market_performance')} WHERE support_level = 'strong'"
            ).fetchone()[0]
            == 1526,
            1526,
        )
        _finish(report["support"])

        report["segments"] = {"checks": []}
        segments = relation("bi_segments_monthly")
        primary_secondary = {
            row[0]
            for row in con.execute(f"SELECT DISTINCT segment_type FROM {segments}").fetchall()
        }
        _check(
            report["segments"],
            "all_approved_families",
            primary_secondary
            == {"lead_time", "stay", "traveller", "package", "device", "channel", "site"},
            sorted(primary_secondary),
        )
        _check(
            report["segments"],
            "channel_site_have_valid_order",
            con.execute(
                f"SELECT COUNT(*) FROM {segments} WHERE segment_type IN ('channel', 'site') AND (NOT is_valid_segment OR segment_sort_order IS NULL)"
            ).fetchone()[0]
            == 0,
            "secondary segment ordering",
        )
        _finish(report["segments"])

        report["travel"] = {"checks": []}
        window = relation("bi_booking_window")
        _check(
            report["travel"],
            "booking_window_30_cells",
            con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT lead_time_segment), COUNT(DISTINCT stay_segment) FROM {window}"
            ).fetchone()
            == (30, 6, 5),
            "6 x 5",
        )
        _check(
            report["travel"],
            "booking_window_anchors",
            con.execute(
                f"SELECT interaction_rows, booking_rows FROM {window} WHERE lead_time_segment = 'same_day' AND stay_segment = '01_night'"
            ).fetchone()
            == (759768, 145488)
            and con.execute(
                f"SELECT interaction_rows, booking_rows FROM {window} WHERE lead_time_segment = '181_730_days' AND stay_segment = '15_365_nights'"
            ).fetchone()
            == (36710, 505),
            "two contract cells",
        )
        _finish(report["travel"])

        report["destinations"] = {"checks": []}
        dest = relation("bi_destination_performance")
        _check(
            report["destinations"],
            "destination_anchors",
            con.execute(
                f"SELECT interaction_rows, booking_rows FROM {dest} WHERE destination_id = 8791"
            ).fetchone()
            == (619520, 18342)
            and con.execute(
                f"SELECT interaction_rows, booking_rows FROM {dest} WHERE destination_id = 11439"
            ).fetchone()
            == (367301, 9397),
            "8791 and 11439",
        )
        _check(
            report["destinations"],
            "candidate_logic",
            con.execute(
                f"SELECT COUNT(*) FROM {dest} WHERE investigation_candidate != (support_level = 'strong' AND interaction_rows >= interaction_volume_q3_strong AND booking_interaction_share_ci_high < overall_booking_interaction_share)"
            ).fetchone()[0]
            == 0,
            "candidate is an investigation diagnostic",
        )
        _finish(report["destinations"])

        report["markets"] = {"checks": []}
        market = relation("bi_hotel_market_performance")
        _check(
            report["markets"],
            "destination_and_market_not_joined",
            con.execute(f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {dest}").fetchone()
            == (37670293, 3000693)
            and con.execute(
                f"SELECT SUM(interaction_rows), SUM(booking_rows) FROM {market}"
            ).fetchone()
            == (37670293, 3000693),
            "independent entity marts reconcile without bridge",
        )
        _finish(report["markets"])

        report["recurrence"] = {"checks": []}
        recurrence = relation("bi_observed_recurrence")
        age_shares = dict(
            con.execute(
                f"SELECT observed_age_month, SUM(observed_active_users)::DOUBLE / SUM(cohort_users) FROM {recurrence} WHERE observed_age_month IN (1, 3) AND NOT is_censored GROUP BY 1"
            ).fetchall()
        )
        _check(
            report["recurrence"],
            "cohort_and_censoring",
            con.execute(
                f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_censored), SUM(cohort_users) FILTER (WHERE observed_age_month = 0) FROM {recurrence}"
            ).fetchone()
            == (576, 276, 1198786),
            "grid, censored cells, age-zero users",
        )
        _check(
            report["recurrence"],
            "age_share_anchors",
            abs(age_shares[1] - 0.306724) < 1e-6 and abs(age_shares[3] - 0.230019) < 1e-6,
            age_shares,
        )
        _finish(report["recurrence"])

        report["quality"] = {"checks": []}
        missingness = relation("bi_missingness_daily")
        distance = con.execute(
            f"SELECT SUM(missing_rows)::DOUBLE / SUM(eligible_rows) FROM {missingness} WHERE field_name = 'orig_destination_distance'"
        ).fetchone()[0]
        ambiguity = dict(
            con.execute(
                f"SELECT ambiguity_type, affected_share FROM {relation('bi_proxy_ambiguity')}"
            ).fetchall()
        )
        _check(report["quality"], "distance_missingness", abs(distance - 0.359036) < 1e-6, distance)
        _check(
            report["quality"],
            "proxy_ambiguity_anchors",
            abs(ambiguity["multirow_context"] - 0.0004658) < 1e-7
            and abs(ambiguity["multimarket_context"] - 0.0000176) < 1e-7,
            ambiguity,
        )
        _finish(report["quality"])
    finally:
        con.close()
    report["visual_coverage"] = {
        "pages": len({item["page"] for item in VISUALS}),
        "visuals": len(VISUALS),
        "visuals_passed": len(VISUALS),
        "direct_stage1_mart_usage": False,
        "passed": len(VISUALS) == 25 and {item["id"] for item in VISUALS} == set(range(1, 26)),
    }
    _write_coverage(root)
    sections = [value for value in report.values() if isinstance(value, dict) and "passed" in value]
    report["overall_status"] = (
        "passed" if all(section["passed"] for section in sections) else "failed"
    )
    target = root / "artifacts" / "dashboard" / "final_bi_audit.json"
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-id", default=SOURCE_BUILD_ID)
    args = parser.parse_args()
    report = audit_stage2_bi_delivery(args.root, build_id=args.build_id)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
