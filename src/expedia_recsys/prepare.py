from __future__ import annotations

from pathlib import Path

from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect, sql_path

TRAIN_FILE_NAMES = ("train.csv", "train.csv.gz")
TEST_FILE_NAMES = ("test.csv", "test.csv.gz")
DESTINATIONS_FILE_NAMES = ("destinations.csv", "destinations.csv.gz")


def _find_file(directory: Path, candidates: tuple[str, ...]) -> Path:
    for name in candidates:
        path = directory / name
        if path.exists():
            return path
    expected = ", ".join(candidates)
    raise FileNotFoundError(f"No input file found in {directory}. Expected one of: {expected}")


def _copy_query_to_parquet(con: object, query: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    con.execute(
        f"""
        COPY (
            {query}
        ) TO '{sql_path(target)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )


def prepare_data(
    paths: ProjectPaths,
    *,
    threads: int = 4,
    memory_limit: str = "8GB",
) -> dict[str, Path]:
    """Normalize Kaggle CSV/CSV.GZ files and convert them to typed Parquet files."""
    paths.ensure_directories()
    train_source = _find_file(paths.raw_dir, TRAIN_FILE_NAMES)
    test_source = _find_file(paths.raw_dir, TEST_FILE_NAMES)
    destinations_source = _find_file(paths.raw_dir, DESTINATIONS_FILE_NAMES)

    train_target = paths.processed_dir / "train.parquet"
    test_target = paths.processed_dir / "test.parquet"
    destinations_target = paths.processed_dir / "destinations.parquet"
    database_path = paths.processed_dir / "stage1.duckdb"

    con = connect(database_path, threads=threads, memory_limit=memory_limit)
    try:
        train_query = f"""
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
            TRY_CAST(srch_destination_type_id AS SMALLINT) AS srch_destination_type_id,
            TRY_CAST(is_booking AS TINYINT) AS is_booking,
            TRY_CAST(cnt AS INTEGER) AS cnt,
            TRY_CAST(hotel_continent AS SMALLINT) AS hotel_continent,
            TRY_CAST(hotel_country AS INTEGER) AS hotel_country,
            TRY_CAST(hotel_market AS INTEGER) AS hotel_market,
            TRY_CAST(hotel_cluster AS SMALLINT) AS hotel_cluster
        FROM read_csv(
            '{sql_path(train_source)}',
            header = true,
            all_varchar = true,
            nullstr = ''
        )
        WHERE TRY_CAST(date_time AS TIMESTAMP) IS NOT NULL
          AND TRY_CAST(hotel_cluster AS SMALLINT) BETWEEN 0 AND 99
        """
        print(f"[prepare] {train_source.name} -> {train_target.name}")
        _copy_query_to_parquet(con, train_query, train_target)

        test_query = f"""
        SELECT
            TRY_CAST(id AS BIGINT) AS id,
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
            TRY_CAST(srch_destination_type_id AS SMALLINT) AS srch_destination_type_id,
            TRY_CAST(hotel_continent AS SMALLINT) AS hotel_continent,
            TRY_CAST(hotel_country AS INTEGER) AS hotel_country,
            TRY_CAST(hotel_market AS INTEGER) AS hotel_market
        FROM read_csv(
            '{sql_path(test_source)}',
            header = true,
            all_varchar = true,
            nullstr = ''
        )
        WHERE TRY_CAST(id AS BIGINT) IS NOT NULL
        """
        print(f"[prepare] {test_source.name} -> {test_target.name}")
        _copy_query_to_parquet(con, test_query, test_target)

        destination_columns = ["TRY_CAST(srch_destination_id AS INTEGER) AS srch_destination_id"]
        destination_columns.extend(
            f"TRY_CAST(d{i} AS REAL) AS d{i}" for i in range(1, 150)
        )
        destinations_query = f"""
        SELECT
            {', '.join(destination_columns)}
        FROM read_csv(
            '{sql_path(destinations_source)}',
            header = true,
            all_varchar = true,
            nullstr = ''
        )
        WHERE TRY_CAST(srch_destination_id AS INTEGER) IS NOT NULL
        """
        print(f"[prepare] {destinations_source.name} -> {destinations_target.name}")
        _copy_query_to_parquet(con, destinations_query, destinations_target)

        train_rows = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{sql_path(train_target)}')"
        ).fetchone()[0]
        test_rows = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{sql_path(test_target)}')"
        ).fetchone()[0]
        destination_rows = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{sql_path(destinations_target)}')"
        ).fetchone()[0]
        print(
            "[prepare] complete: "
            f"train={train_rows:,}, test={test_rows:,}, destinations={destination_rows:,}"
        )
    finally:
        con.close()

    return {
        "train": train_target,
        "test": test_target,
        "destinations": destinations_target,
    }
