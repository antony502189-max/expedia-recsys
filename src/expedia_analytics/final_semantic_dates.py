from __future__ import annotations

from typing import Any


def _date_policy(contract: dict[str, Any]) -> tuple[int, int]:
    policy = contract["semantic_date_policy"]
    return (
        int(policy["maximum_lead_time_days"]),
        int(policy["maximum_stay_nights"]),
    )


def _apply_trip_date_semantics(con: Any, contract: dict[str, Any]) -> None:
    """Classify parse-valid trip dates without dropping source interactions."""
    max_lead, max_stay = _date_policy(contract)
    con.execute(
        """
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN is_chronologically_valid_lead_time BOOLEAN;
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN is_chronologically_valid_stay_dates BOOLEAN;
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN is_plausible_lead_time BOOLEAN;
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN is_plausible_stay_dates BOOLEAN;
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN is_plausible_trip_dates BOOLEAN;
        ALTER TABLE analytics.fct_hotel_interactions
            ADD COLUMN trip_date_quality VARCHAR;
        """
    )
    con.execute(
        f"""
        UPDATE analytics.fct_hotel_interactions
        SET
            is_chronologically_valid_lead_time =
                checkin_date IS NOT NULL AND lead_time_days >= 0,
            is_chronologically_valid_stay_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND stay_nights > 0,
            is_plausible_lead_time =
                checkin_date IS NOT NULL AND lead_time_days BETWEEN 0 AND {max_lead},
            is_plausible_stay_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND stay_nights BETWEEN 1 AND {max_stay},
            is_plausible_trip_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND lead_time_days BETWEEN 0 AND {max_lead}
                AND stay_nights BETWEEN 1 AND {max_stay},
            has_valid_lead_time =
                checkin_date IS NOT NULL AND lead_time_days BETWEEN 0 AND {max_lead},
            has_valid_stay_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND stay_nights BETWEEN 1 AND {max_stay},
            lead_time_segment = CASE
                WHEN checkin_date IS NULL THEN 'missing'
                WHEN lead_time_days < 0 THEN 'invalid_negative'
                WHEN lead_time_days > {max_lead} THEN 'out_of_scope_gt_{max_lead}'
                WHEN lead_time_days = 0 THEN 'same_day'
                WHEN lead_time_days <= 7 THEN '01_07_days'
                WHEN lead_time_days <= 30 THEN '08_30_days'
                WHEN lead_time_days <= 90 THEN '31_90_days'
                WHEN lead_time_days <= 180 THEN '91_180_days'
                ELSE '181_{max_lead}_days'
            END,
            stay_segment = CASE
                WHEN checkin_date IS NULL OR checkout_date IS NULL THEN 'missing'
                WHEN stay_nights <= 0 THEN 'invalid_nonpositive'
                WHEN stay_nights > {max_stay} THEN 'out_of_scope_gt_{max_stay}'
                WHEN stay_nights = 1 THEN '01_night'
                WHEN stay_nights <= 3 THEN '02_03_nights'
                WHEN stay_nights <= 7 THEN '04_07_nights'
                WHEN stay_nights <= 14 THEN '08_14_nights'
                ELSE '15_{max_stay}_nights'
            END,
            trip_date_quality = CASE
                WHEN checkin_date IS NULL THEN 'missing_checkin'
                WHEN lead_time_days < 0 THEN 'checkin_before_event'
                WHEN lead_time_days > {max_lead} THEN 'lead_time_out_of_scope'
                WHEN checkout_date IS NULL THEN 'missing_checkout'
                WHEN stay_nights <= 0 THEN 'checkout_not_after_checkin'
                WHEN stay_nights > {max_stay} THEN 'stay_out_of_scope'
                ELSE 'plausible'
            END
        """
    )

    con.execute(
        """
        ALTER TABLE analytics.fct_proxy_search_contexts
            ADD COLUMN is_plausible_lead_time BOOLEAN;
        ALTER TABLE analytics.fct_proxy_search_contexts
            ADD COLUMN is_plausible_stay_dates BOOLEAN;
        ALTER TABLE analytics.fct_proxy_search_contexts
            ADD COLUMN is_plausible_trip_dates BOOLEAN;
        ALTER TABLE analytics.fct_proxy_search_contexts
            ADD COLUMN trip_date_quality VARCHAR;
        """
    )
    con.execute(
        f"""
        UPDATE analytics.fct_proxy_search_contexts
        SET
            is_plausible_lead_time =
                checkin_date IS NOT NULL AND lead_time_days BETWEEN 0 AND {max_lead},
            is_plausible_stay_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND stay_nights BETWEEN 1 AND {max_stay},
            is_plausible_trip_dates =
                checkin_date IS NOT NULL
                AND checkout_date IS NOT NULL
                AND lead_time_days BETWEEN 0 AND {max_lead}
                AND stay_nights BETWEEN 1 AND {max_stay},
            lead_time_segment = CASE
                WHEN checkin_date IS NULL THEN 'missing'
                WHEN lead_time_days < 0 THEN 'invalid_negative'
                WHEN lead_time_days > {max_lead} THEN 'out_of_scope_gt_{max_lead}'
                WHEN lead_time_days = 0 THEN 'same_day'
                WHEN lead_time_days <= 7 THEN '01_07_days'
                WHEN lead_time_days <= 30 THEN '08_30_days'
                WHEN lead_time_days <= 90 THEN '31_90_days'
                WHEN lead_time_days <= 180 THEN '91_180_days'
                ELSE '181_{max_lead}_days'
            END,
            stay_segment = CASE
                WHEN checkin_date IS NULL OR checkout_date IS NULL THEN 'missing'
                WHEN stay_nights <= 0 THEN 'invalid_nonpositive'
                WHEN stay_nights > {max_stay} THEN 'out_of_scope_gt_{max_stay}'
                WHEN stay_nights = 1 THEN '01_night'
                WHEN stay_nights <= 3 THEN '02_03_nights'
                WHEN stay_nights <= 7 THEN '04_07_nights'
                WHEN stay_nights <= 14 THEN '08_14_nights'
                ELSE '15_{max_stay}_nights'
            END,
            trip_date_quality = CASE
                WHEN checkin_date IS NULL THEN 'missing_checkin'
                WHEN lead_time_days < 0 THEN 'checkin_before_event'
                WHEN lead_time_days > {max_lead} THEN 'lead_time_out_of_scope'
                WHEN checkout_date IS NULL THEN 'missing_checkout'
                WHEN stay_nights <= 0 THEN 'checkout_not_after_checkin'
                WHEN stay_nights > {max_stay} THEN 'stay_out_of_scope'
                ELSE 'plausible'
            END
        """
    )


def _replace_date_dimension(con: Any) -> None:
    """Build a role-playing date spine from event and plausible trip dates only."""
    con.execute("DROP TABLE analytics.dim_date")
    con.execute(
        """
        CREATE TABLE analytics.dim_date AS
        WITH event_dates AS (
            SELECT DISTINCT event_date AS date_day
            FROM analytics.fct_hotel_interactions
        ), checkin_dates AS (
            SELECT DISTINCT checkin_date AS date_day
            FROM analytics.fct_hotel_interactions
            WHERE is_plausible_lead_time
        ), checkout_dates AS (
            SELECT DISTINCT checkout_date AS date_day
            FROM analytics.fct_hotel_interactions
            WHERE is_plausible_trip_dates
        ), eligible_dates AS (
            SELECT date_day FROM event_dates
            UNION
            SELECT date_day FROM checkin_dates
            UNION
            SELECT date_day FROM checkout_dates
        ), bounds AS (
            SELECT MIN(date_day) AS min_date, MAX(date_day) AS max_date
            FROM eligible_dates
        )
        SELECT
            day_value::DATE AS date_day,
            EXTRACT(year FROM day_value)::SMALLINT AS calendar_year,
            EXTRACT(quarter FROM day_value)::TINYINT AS calendar_quarter,
            EXTRACT(month FROM day_value)::TINYINT AS calendar_month,
            EXTRACT(week FROM day_value)::TINYINT AS iso_week,
            EXTRACT(isodow FROM day_value)::TINYINT AS iso_day_of_week,
            EXTRACT(isodow FROM day_value) IN (6, 7) AS is_weekend,
            DATE_TRUNC('week', day_value)::DATE AS week_start,
            DATE_TRUNC('month', day_value)::DATE AS month_start,
            DATE_TRUNC('quarter', day_value)::DATE AS quarter_start,
            DATE_TRUNC('year', day_value)::DATE AS year_start,
            e.date_day IS NOT NULL AS is_observed_event_date,
            ci.date_day IS NOT NULL AS is_plausible_checkin_date,
            co.date_day IS NOT NULL AS is_plausible_checkout_date
        FROM bounds,
             GENERATE_SERIES(min_date, max_date, INTERVAL 1 DAY) AS dates(day_value)
        LEFT JOIN event_dates e ON e.date_day = day_value::DATE
        LEFT JOIN checkin_dates ci ON ci.date_day = day_value::DATE
        LEFT JOIN checkout_dates co ON co.date_day = day_value::DATE
        """
    )


def _replace_trip_segment_definitions(con: Any, contract: dict[str, Any]) -> None:
    max_lead, max_stay = _date_policy(contract)
    con.execute(
        "DELETE FROM analytics.dim_segment_definition "
        "WHERE segment_type IN ('lead_time', 'stay')"
    )
    con.execute(
        f"""
        INSERT INTO analytics.dim_segment_definition VALUES
            ('lead_time', 'same_day', 1, 'Check-in on event date'),
            ('lead_time', '01_07_days', 2, 'One to seven days'),
            ('lead_time', '08_30_days', 3, 'Eight to thirty days'),
            ('lead_time', '31_90_days', 4, 'Thirty-one to ninety days'),
            ('lead_time', '91_180_days', 5, 'Ninety-one to one hundred eighty days'),
            ('lead_time', '181_{max_lead}_days', 6,
             'One hundred eighty-one to {max_lead} days'),
            ('lead_time', 'invalid_negative', 97, 'Check-in before event date'),
            ('lead_time', 'out_of_scope_gt_{max_lead}', 98,
             'Parse-valid lead time above the semantic safety bound'),
            ('lead_time', 'missing', 99, 'Missing check-in date'),
            ('stay', '01_night', 1, 'One night'),
            ('stay', '02_03_nights', 2, 'Two to three nights'),
            ('stay', '04_07_nights', 3, 'Four to seven nights'),
            ('stay', '08_14_nights', 4, 'Eight to fourteen nights'),
            ('stay', '15_{max_stay}_nights', 5, 'Fifteen to {max_stay} nights'),
            ('stay', 'invalid_nonpositive', 97, 'Checkout not after check-in'),
            ('stay', 'out_of_scope_gt_{max_stay}', 98,
             'Parse-valid stay above the semantic safety bound'),
            ('stay', 'missing', 99, 'Missing trip date')
        """
    )


def _extend_data_quality_summary(con: Any) -> None:
    con.execute(
        """
        INSERT INTO analytics.dm_data_quality_summary
        SELECT
            'trip_date_quality:' || trip_date_quality AS quality_rule,
            COUNT(*)::BIGINT AS affected_rows,
            (SELECT COUNT(*) FROM analytics.fct_hotel_interactions)::BIGINT
                AS denominator_rows,
            CASE WHEN trip_date_quality = 'plausible' THEN 'info' ELSE 'warning' END
                AS severity,
            safe_rate(
                COUNT(*),
                (SELECT COUNT(*) FROM analytics.fct_hotel_interactions)
            ) AS affected_share
        FROM analytics.fct_hotel_interactions
        GROUP BY trip_date_quality;

        INSERT INTO analytics.dm_data_quality_summary
        SELECT
            'date_spine_calendar_days',
            COUNT(*)::BIGINT,
            COUNT(*)::BIGINT,
            'info',
            1.0
        FROM analytics.dim_date;
        """
    )


def _semantic_date_quality_gates(
    con: Any, contract: dict[str, Any]
) -> list[dict[str, Any]]:
    max_lead, max_stay = _date_policy(contract)
    checks: list[dict[str, Any]] = []

    def scalar(query: str) -> Any:
        row = con.execute(query).fetchone()
        return None if row is None else row[0]

    def add(name: str, actual: Any, expected: Any, passed: bool) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "actual": actual,
                "expected": expected,
            }
        )

    null_quality = int(
        scalar(
            "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
            "WHERE trip_date_quality IS NULL"
        )
    )
    add("trip_date_quality_is_complete", null_quality, 0, null_quality == 0)

    classified_rows = int(
        scalar(
            "SELECT SUM(affected_rows) FROM analytics.dm_data_quality_summary "
            "WHERE quality_rule LIKE 'trip_date_quality:%'"
        )
    )
    fact_rows = int(scalar("SELECT COUNT(*) FROM analytics.fct_hotel_interactions"))
    add(
        "trip_date_quality_reconciles_to_fact",
        classified_rows,
        fact_rows,
        classified_rows == fact_rows,
    )

    expected_bounds = con.execute(
        """
        WITH eligible_dates AS (
            SELECT event_date AS date_day FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT checkin_date FROM analytics.fct_hotel_interactions
            WHERE is_plausible_lead_time
            UNION ALL
            SELECT checkout_date FROM analytics.fct_hotel_interactions
            WHERE is_plausible_trip_dates
        )
        SELECT MIN(date_day), MAX(date_day),
               DATE_DIFF('day', MIN(date_day), MAX(date_day)) + 1
        FROM eligible_dates
        """
    ).fetchone()
    actual_bounds = con.execute(
        "SELECT MIN(date_day), MAX(date_day), COUNT(*) FROM analytics.dim_date"
    ).fetchone()
    add(
        "date_spine_matches_semantically_eligible_bounds",
        list(actual_bounds),
        list(expected_bounds),
        actual_bounds == expected_bounds,
    )

    seasonality_rows = int(
        scalar("SELECT SUM(interaction_rows) FROM analytics.dm_checkin_seasonality") or 0
    )
    plausible_checkins = int(
        scalar(
            "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
            "WHERE is_plausible_lead_time"
        )
    )
    add(
        "checkin_seasonality_uses_only_plausible_checkins",
        seasonality_rows,
        plausible_checkins,
        seasonality_rows == plausible_checkins,
    )

    booking_window_rows = int(
        scalar("SELECT SUM(interaction_rows) FROM analytics.dm_booking_window") or 0
    )
    plausible_trips = int(
        scalar(
            "SELECT COUNT(*) FROM analytics.fct_hotel_interactions "
            "WHERE is_plausible_trip_dates"
        )
    )
    add(
        "booking_window_uses_only_plausible_trip_dates",
        booking_window_rows,
        plausible_trips,
        booking_window_rows == plausible_trips,
    )

    leaked_extremes = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM analytics.dim_date d
            WHERE d.date_day IN (
                SELECT checkin_date
                FROM analytics.fct_hotel_interactions
                WHERE lead_time_days > {max_lead}
                UNION
                SELECT checkout_date
                FROM analytics.fct_hotel_interactions
                WHERE stay_nights > {max_stay}
                   OR lead_time_days > {max_lead}
            )
              AND NOT EXISTS (
                  SELECT 1
                  FROM analytics.fct_hotel_interactions i
                  WHERE i.event_date = d.date_day
                     OR (i.checkin_date = d.date_day AND i.is_plausible_lead_time)
                     OR (i.checkout_date = d.date_day AND i.is_plausible_trip_dates)
              )
            """
        )
    )
    add(
        "out_of_scope_trip_dates_do_not_expand_date_spine",
        leaked_extremes,
        0,
        leaked_extremes == 0,
    )
    return checks
