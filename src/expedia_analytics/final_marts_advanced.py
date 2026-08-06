from __future__ import annotations

from typing import Any


def _create_advanced_marts(con: Any) -> None:
    con.execute(
        """
        CREATE TABLE analytics.dm_observed_recurrence AS
        WITH first_seen AS (
            SELECT user_id, MIN(event_month) AS first_observed_month
            FROM analytics.fct_user_day
            GROUP BY user_id
        ), user_month AS (
            SELECT DISTINCT user_id, event_month AS activity_month
            FROM analytics.fct_user_day
        ), cohort_size AS (
            SELECT first_observed_month, COUNT(*)::BIGINT AS cohort_users
            FROM first_seen
            GROUP BY first_observed_month
        ), observed AS (
            SELECT
                f.first_observed_month,
                u.activity_month,
                DATE_DIFF('month', f.first_observed_month, u.activity_month)::INTEGER
                    AS observed_age_month,
                COUNT(DISTINCT u.user_id)::BIGINT AS observed_active_users,
                COUNT(DISTINCT u.user_id) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM analytics.fct_user_day d
                        WHERE d.user_id = u.user_id
                          AND d.event_month = u.activity_month
                          AND d.has_booking
                    )
                )::BIGINT AS observed_booking_users
            FROM user_month u
            JOIN first_seen f USING (user_id)
            GROUP BY f.first_observed_month, u.activity_month
        ), bounds AS (
            SELECT MAX(event_month) AS max_observed_month FROM analytics.fct_user_day
        )
        SELECT
            o.first_observed_month,
            o.activity_month,
            o.observed_age_month,
            c.cohort_users,
            o.observed_active_users,
            safe_rate(o.observed_active_users, c.cohort_users) AS observed_recurrence_share,
            o.observed_booking_users,
            safe_rate(o.observed_booking_users, o.observed_active_users)
                AS booking_user_share_among_observed_active,
            DATE_DIFF('month', o.first_observed_month, b.max_observed_month)
                < (SELECT MAX(observed_age_month) FROM observed) AS is_right_censored,
            DATE_DIFF('month', o.first_observed_month, b.max_observed_month)
                AS observable_horizon_months
        FROM observed o
        JOIN cohort_size c USING (first_observed_month)
        CROSS JOIN bounds b;
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dm_missingness_daily AS
        WITH long_form AS (
            SELECT event_date, 'user_id' AS field_name, user_id IS NULL AS is_missing
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'orig_destination_distance', orig_destination_distance IS NULL
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'checkin_date', checkin_date IS NULL
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'checkout_date', checkout_date IS NULL
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'srch_destination_id', srch_destination_id IS NULL
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'hotel_market', hotel_market IS NULL
            FROM analytics.fct_hotel_interactions
            UNION ALL
            SELECT event_date, 'similar_event_count', similar_event_count IS NULL
            FROM analytics.fct_hotel_interactions
        )
        SELECT
            event_date,
            field_name,
            COUNT(*)::BIGINT AS eligible_rows,
            COUNT(*) FILTER (WHERE is_missing)::BIGINT AS missing_rows,
            safe_rate(COUNT(*) FILTER (WHERE is_missing), COUNT(*)) AS missing_share
        FROM long_form
        GROUP BY event_date, field_name;

        CREATE TABLE analytics.dm_proxy_context_ambiguity AS
        SELECT * FROM (VALUES
            ('multirow_context',
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts WHERE interaction_rows > 1),
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts)),
            ('multicluster_context',
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts
              WHERE distinct_hotel_clusters > 1),
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts)),
            ('multimarket_context',
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts
              WHERE distinct_hotel_markets > 1),
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts)),
            ('multibooking_context',
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts WHERE booking_rows > 1),
             (SELECT COUNT(*) FROM analytics.fct_proxy_search_contexts))
        ) AS t(ambiguity_type, affected_contexts, proxy_contexts);
        ALTER TABLE analytics.dm_proxy_context_ambiguity ADD COLUMN affected_share DOUBLE;
        UPDATE analytics.dm_proxy_context_ambiguity
        SET affected_share = safe_rate(affected_contexts, proxy_contexts);
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dm_booking_population_drift AS
        WITH train_booking AS (
            SELECT
                'train_booking' AS dataset,
                event_month AS period_month,
                is_mobile::VARCHAR AS device,
                is_package::VARCHAR AS package,
                channel::VARCHAR AS channel,
                srch_destination_type_id::VARCHAR AS destination_type,
                hotel_country::VARCHAR AS hotel_country,
                hotel_market::VARCHAR AS hotel_market
            FROM analytics.fct_hotel_interactions
            WHERE is_booking = 1
        ), test_booking AS (
            SELECT
                'test_booking' AS dataset,
                DATE_TRUNC('month', date_time)::DATE AS period_month,
                is_mobile::VARCHAR AS device,
                is_package::VARCHAR AS package,
                channel::VARCHAR AS channel,
                srch_destination_type_id::VARCHAR AS destination_type,
                hotel_country::VARCHAR AS hotel_country,
                hotel_market::VARCHAR AS hotel_market
            FROM staging.stg_test_accepted
        ), combined AS (
            SELECT * FROM train_booking
            UNION ALL
            SELECT * FROM test_booking
        ), long_form AS (
            SELECT dataset, period_month, 'device' AS dimension_name,
                   COALESCE(device, 'missing') AS dimension_value FROM combined
            UNION ALL
            SELECT dataset, period_month, 'package', COALESCE(package, 'missing') FROM combined
            UNION ALL
            SELECT dataset, period_month, 'channel', COALESCE(channel, 'missing') FROM combined
            UNION ALL
            SELECT dataset, period_month, 'destination_type',
                   COALESCE(destination_type, 'missing') FROM combined
            UNION ALL
            SELECT dataset, period_month, 'hotel_country', COALESCE(hotel_country, 'missing')
            FROM combined
            UNION ALL
            SELECT dataset, period_month, 'hotel_market', COALESCE(hotel_market, 'missing')
            FROM combined
        )
        SELECT
            dataset,
            period_month,
            dimension_name,
            dimension_value,
            COUNT(*)::BIGINT AS booking_population_rows,
            safe_rate(
                COUNT(*),
                SUM(COUNT(*)) OVER (PARTITION BY dataset, period_month, dimension_name)
            ) AS share_within_booking_population
        FROM long_form
        GROUP BY dataset, period_month, dimension_name, dimension_value;

        CREATE TABLE analytics.dm_booking_population_drift_summary AS
        WITH aggregate_share AS (
            SELECT
                dataset,
                dimension_name,
                dimension_value,
                safe_rate(
                    SUM(booking_population_rows),
                    SUM(SUM(booking_population_rows)) OVER (PARTITION BY dataset, dimension_name)
                ) AS population_share
            FROM analytics.dm_booking_population_drift
            GROUP BY dataset, dimension_name, dimension_value
        ), paired AS (
            SELECT
                COALESCE(t.dimension_name, e.dimension_name) AS dimension_name,
                COALESCE(t.dimension_value, e.dimension_value) AS dimension_value,
                COALESCE(t.population_share, 0.0) AS train_share,
                COALESCE(e.population_share, 0.0) AS test_share
            FROM aggregate_share t
            FULL OUTER JOIN aggregate_share e
              ON t.dimension_name = e.dimension_name
             AND t.dimension_value = e.dimension_value
             AND t.dataset = 'train_booking'
             AND e.dataset = 'test_booking'
            WHERE COALESCE(t.dataset, 'train_booking') = 'train_booking'
              AND COALESCE(e.dataset, 'test_booking') = 'test_booking'
        )
        SELECT
            dimension_name,
            0.5 * SUM(ABS(test_share - train_share)) AS total_variation_distance,
            SUM(
                (test_share - train_share)
                * LN((test_share + 1e-12) / (train_share + 1e-12))
            ) AS population_stability_index,
            COUNT(*)::BIGINT AS compared_categories
        FROM paired
        GROUP BY dimension_name;
        """
    )
    con.execute(
        """
        CREATE TABLE analytics.dm_data_quality_summary AS
        WITH counts AS (
            SELECT
                (SELECT COUNT(*) FROM raw.train_landing) AS raw_train_rows,
                (SELECT COUNT(*) FROM staging.stg_train_accepted) AS accepted_train_rows,
                (SELECT COUNT(*) FROM staging.quarantine_train) AS quarantined_train_rows,
                (SELECT COUNT(*) FROM raw.test_landing) AS raw_test_rows,
                (SELECT COUNT(*) FROM staging.stg_test_accepted) AS accepted_test_rows,
                (SELECT COUNT(*) FROM staging.quarantine_test) AS quarantined_test_rows,
                (SELECT COUNT(*) FROM raw.destinations_landing) AS raw_destination_rows,
                (SELECT COUNT(*) FROM staging.stg_destinations_accepted)
                    AS accepted_destination_rows,
                (SELECT COUNT(*) FROM staging.quarantine_destinations)
                    AS quarantined_destination_rows
        )
        SELECT * FROM (VALUES
            ('raw_train_rows', (SELECT raw_train_rows FROM counts),
             (SELECT raw_train_rows FROM counts), 'info'),
            ('accepted_train_rows', (SELECT accepted_train_rows FROM counts),
             (SELECT raw_train_rows FROM counts), 'info'),
            ('quarantined_train_rows', (SELECT quarantined_train_rows FROM counts),
             (SELECT raw_train_rows FROM counts), 'warning'),
            ('raw_train_reconciliation_gap',
             (SELECT raw_train_rows - accepted_train_rows - quarantined_train_rows FROM counts),
             (SELECT raw_train_rows FROM counts), 'critical'),
            ('raw_test_reconciliation_gap',
             (SELECT raw_test_rows - accepted_test_rows - quarantined_test_rows FROM counts),
             (SELECT raw_test_rows FROM counts), 'critical'),
            ('raw_destination_reconciliation_gap',
             (SELECT raw_destination_rows - accepted_destination_rows
                     - quarantined_destination_rows FROM counts),
             (SELECT raw_destination_rows FROM counts), 'critical')
        ) AS t(quality_rule, affected_rows, denominator_rows, severity);
        ALTER TABLE analytics.dm_data_quality_summary ADD COLUMN affected_share DOUBLE;
        UPDATE analytics.dm_data_quality_summary
        SET affected_share = safe_rate(affected_rows, denominator_rows);
        """
    )
