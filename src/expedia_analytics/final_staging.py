from __future__ import annotations

from pathlib import Path
from typing import Any

from expedia_analytics.config import AnalyticsPaths
from expedia_analytics.contracts import DESTINATION_COLUMNS, TEST_COLUMNS, TRAIN_COLUMNS, ColumnSpec
from expedia_analytics.final_common import (
    _fingerprint_expr,
    _read_csv_relation,
    _reject_reason_expr,
    _typed_expr,
)


def _create_raw_landings(con: Any, paths: AnalyticsPaths) -> dict[str, Path]:
    sources = {
        "train": paths.find_raw_train(),
        "test": paths.find_raw_test(),
        "destinations": paths.find_raw_destinations(),
    }
    con.execute("CREATE SCHEMA raw")
    for name, path in sources.items():
        con.execute(
            f"""
            CREATE TABLE raw.{name}_landing AS
            SELECT
                ROW_NUMBER() OVER ()::BIGINT AS source_scan_ordinal,
                *
            FROM {_read_csv_relation(path)}
            """
        )
    return sources


def _create_typed_staging(
    con: Any,
    *,
    source_name: str,
    accepted_name: str,
    quarantine_name: str,
    columns: tuple[ColumnSpec, ...],
    extra_select: str = "",
) -> None:
    fingerprint = _fingerprint_expr(columns)
    reasons = ", ".join(_reject_reason_expr(spec) for spec in columns)
    typed_columns = ",\n".join(
        f"{_typed_expr(spec)} AS \"{spec.name}\"" for spec in columns
    )
    raw_columns = ",\n".join(f'"{spec.name}" AS raw__{spec.name}' for spec in columns)
    con.execute(
        f"""
        CREATE TABLE staging._{source_name}_classified AS
        WITH classified AS (
            SELECT
                source_scan_ordinal,
                filename AS source_file,
                {fingerprint} AS raw_row_fingerprint,
                CONCAT_WS(';', {reasons}) AS reject_reasons,
                {typed_columns},
                {raw_columns}
                {extra_select}
            FROM raw.{source_name}_landing
        ), multiplicity AS (
            SELECT
                *,
                COUNT(*) OVER (PARTITION BY raw_row_fingerprint)::BIGINT
                    AS duplicate_group_size,
                ROW_NUMBER() OVER (
                    PARTITION BY raw_row_fingerprint ORDER BY source_scan_ordinal
                )::BIGINT AS duplicate_occurrence
            FROM classified
        )
        SELECT * FROM multiplicity
        """
    )
    typed_names = ", ".join(f'"{spec.name}"' for spec in columns)
    con.execute(
        f"""
        CREATE TABLE staging.{accepted_name} AS
        SELECT
            source_scan_ordinal,
            source_file,
            raw_row_fingerprint,
            duplicate_group_size,
            duplicate_occurrence,
            {typed_names}
            {extra_select.replace(' AS ', ' AS ') if extra_select else ''}
        FROM staging._{source_name}_classified
        WHERE reject_reasons = ''
        """
    )
    con.execute(
        f"""
        CREATE TABLE staging.{quarantine_name} AS
        SELECT * EXCLUDE ({typed_names})
        FROM staging._{source_name}_classified
        WHERE reject_reasons <> ''
        """
    )
    con.execute(
        f"""
        CREATE TABLE staging.meta_{source_name}_multiset_reconciliation AS
        WITH raw_counts AS (
            SELECT raw_row_fingerprint, COUNT(*)::BIGINT AS raw_count
            FROM staging._{source_name}_classified
            GROUP BY raw_row_fingerprint
        ), output_counts AS (
            SELECT raw_row_fingerprint, COUNT(*)::BIGINT AS output_count
            FROM (
                SELECT raw_row_fingerprint FROM staging.{accepted_name}
                UNION ALL
                SELECT raw_row_fingerprint FROM staging.{quarantine_name}
            )
            GROUP BY raw_row_fingerprint
        )
        SELECT
            COALESCE(r.raw_row_fingerprint, o.raw_row_fingerprint) AS raw_row_fingerprint,
            COALESCE(r.raw_count, 0) AS raw_count,
            COALESCE(o.output_count, 0) AS output_count,
            COALESCE(r.raw_count, 0) = COALESCE(o.output_count, 0) AS reconciles
        FROM raw_counts r
        FULL OUTER JOIN output_counts o USING (raw_row_fingerprint)
        """
    )
    con.execute(f"DROP TABLE staging._{source_name}_classified")


def _create_destinations_staging(con: Any) -> None:
    columns = DESTINATION_COLUMNS
    fingerprint = _fingerprint_expr(columns)
    reasons = ", ".join(_reject_reason_expr(spec) for spec in columns)
    typed_columns = ",\n".join(
        f"{_typed_expr(spec)} AS \"{spec.name}\"" for spec in columns
    )
    raw_columns = ",\n".join(f'"{spec.name}" AS raw__{spec.name}' for spec in columns)
    con.execute(
        f"""
        CREATE TABLE staging._destinations_classified AS
        WITH classified AS (
            SELECT
                source_scan_ordinal,
                filename AS source_file,
                {fingerprint} AS raw_row_fingerprint,
                CONCAT_WS(';', {reasons}) AS reject_reasons,
                {typed_columns},
                {raw_columns}
            FROM raw.destinations_landing
        )
        SELECT
            *,
            COUNT(*) OVER (PARTITION BY raw_row_fingerprint)::BIGINT
                AS duplicate_group_size,
            ROW_NUMBER() OVER (
                PARTITION BY raw_row_fingerprint ORDER BY source_scan_ordinal
            )::BIGINT AS duplicate_occurrence
        FROM classified
        """
    )
    typed_names = ", ".join(f'"{spec.name}"' for spec in columns)
    con.execute(
        f"""
        CREATE TABLE staging.stg_destinations_accepted AS
        SELECT
            source_scan_ordinal,
            source_file,
            raw_row_fingerprint,
            duplicate_group_size,
            duplicate_occurrence,
            {typed_names}
        FROM staging._destinations_classified
        WHERE reject_reasons = ''
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY srch_destination_id ORDER BY source_scan_ordinal
        ) = 1
        """
    )
    con.execute(
        f"""
        CREATE TABLE staging.quarantine_destinations AS
        WITH classified AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY srch_destination_id ORDER BY source_scan_ordinal
                ) AS destination_occurrence
            FROM staging._destinations_classified
        )
        SELECT * EXCLUDE ({typed_names}, destination_occurrence)
        FROM classified
        WHERE reject_reasons <> '' OR destination_occurrence > 1
        """
    )
    con.execute(
        """
        CREATE TABLE staging.meta_destinations_multiset_reconciliation AS
        WITH raw_counts AS (
            SELECT raw_row_fingerprint, COUNT(*)::BIGINT AS raw_count
            FROM staging._destinations_classified
            GROUP BY raw_row_fingerprint
        ), output_counts AS (
            SELECT raw_row_fingerprint, COUNT(*)::BIGINT AS output_count
            FROM (
                SELECT raw_row_fingerprint FROM staging.stg_destinations_accepted
                UNION ALL
                SELECT raw_row_fingerprint FROM staging.quarantine_destinations
            )
            GROUP BY raw_row_fingerprint
        )
        SELECT
            COALESCE(r.raw_row_fingerprint, o.raw_row_fingerprint) AS raw_row_fingerprint,
            COALESCE(r.raw_count, 0) AS raw_count,
            COALESCE(o.output_count, 0) AS output_count,
            COALESCE(r.raw_count, 0) = COALESCE(o.output_count, 0) AS reconciles
        FROM raw_counts r
        FULL OUTER JOIN output_counts o USING (raw_row_fingerprint)
        """
    )
    con.execute("DROP TABLE staging._destinations_classified")


def _create_staging(con: Any) -> None:
    con.execute("CREATE SCHEMA staging")
    _create_typed_staging(
        con,
        source_name="train",
        accepted_name="stg_train_accepted",
        quarantine_name="quarantine_train",
        columns=TRAIN_COLUMNS,
    )
    _create_typed_staging(
        con,
        source_name="test",
        accepted_name="stg_test_accepted",
        quarantine_name="quarantine_test",
        columns=TEST_COLUMNS,
    )
    _create_destinations_staging(con)
    con.execute(
        """
        ALTER TABLE staging.stg_train_accepted ADD COLUMN event_year SMALLINT;
        ALTER TABLE staging.stg_train_accepted ADD COLUMN event_month_num TINYINT;
        UPDATE staging.stg_train_accepted
        SET event_year = EXTRACT(year FROM date_time)::SMALLINT,
            event_month_num = EXTRACT(month FROM date_time)::TINYINT;
        """
    )
