from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from expedia_recsys.config import ProjectPaths
from expedia_recsys.duck import connect, sql_path


@dataclass(frozen=True, slots=True)
class BaselineMetrics:
    cutoff: str
    history_rows: int
    validation_rows: int
    candidate_recall_at_5: float
    map_at_5: float
    exact_geo_coverage: float
    city_distance_coverage: float


TOP_TABLES_SQL = """
CREATE OR REPLACE TEMP TABLE top_exact_geo AS
WITH scores AS (
    SELECT
        user_location_country,
        user_location_region,
        user_location_city,
        hotel_market,
        orig_destination_distance_key,
        hotel_cluster,
        SUM(event_weight) AS score
    FROM history
    WHERE user_location_country IS NOT NULL
      AND user_location_region IS NOT NULL
      AND user_location_city IS NOT NULL
      AND hotel_market IS NOT NULL
      AND orig_destination_distance_key IS NOT NULL
    GROUP BY ALL
)
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY user_location_country, user_location_region, user_location_city,
                     hotel_market, orig_destination_distance_key
        ORDER BY score DESC, hotel_cluster
    ) AS source_rank
FROM scores
QUALIFY source_rank <= 5;

CREATE OR REPLACE TEMP TABLE top_city_distance AS
WITH scores AS (
    SELECT
        user_location_city,
        orig_destination_distance_key,
        hotel_cluster,
        SUM(event_weight) AS score
    FROM history
    WHERE user_location_city IS NOT NULL
      AND orig_destination_distance_key IS NOT NULL
    GROUP BY ALL
)
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY user_location_city, orig_destination_distance_key
        ORDER BY score DESC, hotel_cluster
    ) AS source_rank
FROM scores
QUALIFY source_rank <= 5;

CREATE OR REPLACE TEMP TABLE top_user_destination AS
WITH scores AS (
    SELECT
        user_id,
        srch_destination_id,
        hotel_country,
        hotel_market,
        hotel_cluster,
        SUM(event_weight) AS score
    FROM history
    WHERE user_id IS NOT NULL
      AND srch_destination_id IS NOT NULL
      AND hotel_country IS NOT NULL
      AND hotel_market IS NOT NULL
    GROUP BY ALL
)
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY user_id, srch_destination_id, hotel_country, hotel_market
        ORDER BY score DESC, hotel_cluster
    ) AS source_rank
FROM scores
QUALIFY source_rank <= 5;

CREATE OR REPLACE TEMP TABLE top_destination_market AS
WITH scores AS (
    SELECT
        srch_destination_id,
        hotel_country,
        hotel_market,
        hotel_cluster,
        SUM(event_weight) AS score
    FROM history
    WHERE srch_destination_id IS NOT NULL
      AND hotel_country IS NOT NULL
      AND hotel_market IS NOT NULL
    GROUP BY ALL
)
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY srch_destination_id, hotel_country, hotel_market
        ORDER BY score DESC, hotel_cluster
    ) AS source_rank
FROM scores
QUALIFY source_rank <= 5;

CREATE OR REPLACE TEMP TABLE top_market AS
WITH scores AS (
    SELECT
        hotel_country,
        hotel_market,
        hotel_cluster,
        SUM(event_weight) AS score
    FROM history
    WHERE hotel_country IS NOT NULL
      AND hotel_market IS NOT NULL
    GROUP BY ALL
)
SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY hotel_country, hotel_market
        ORDER BY score DESC, hotel_cluster
    ) AS source_rank
FROM scores
QUALIFY source_rank <= 5;

CREATE OR REPLACE TEMP TABLE top_global AS
SELECT
    hotel_cluster,
    SUM(event_weight) AS score,
    ROW_NUMBER() OVER (ORDER BY SUM(event_weight) DESC, hotel_cluster) AS source_rank
FROM history
GROUP BY hotel_cluster
QUALIFY source_rank <= 5;
"""


CANDIDATES_SQL = """
CREATE OR REPLACE TEMP TABLE all_candidates AS
SELECT
    q.row_id,
    t.hotel_cluster,
    1 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
JOIN top_exact_geo t
  ON q.user_location_country = t.user_location_country
 AND q.user_location_region = t.user_location_region
 AND q.user_location_city = t.user_location_city
 AND q.hotel_market = t.hotel_market
 AND q.orig_destination_distance_key = t.orig_destination_distance_key

UNION ALL

SELECT
    q.row_id,
    t.hotel_cluster,
    2 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
JOIN top_city_distance t
  ON q.user_location_city = t.user_location_city
 AND q.orig_destination_distance_key = t.orig_destination_distance_key

UNION ALL

SELECT
    q.row_id,
    t.hotel_cluster,
    3 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
JOIN top_user_destination t
  ON q.user_id = t.user_id
 AND q.srch_destination_id = t.srch_destination_id
 AND q.hotel_country = t.hotel_country
 AND q.hotel_market = t.hotel_market

UNION ALL

SELECT
    q.row_id,
    t.hotel_cluster,
    4 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
JOIN top_destination_market t
  ON q.srch_destination_id = t.srch_destination_id
 AND q.hotel_country = t.hotel_country
 AND q.hotel_market = t.hotel_market

UNION ALL

SELECT
    q.row_id,
    t.hotel_cluster,
    5 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
JOIN top_market t
  ON q.hotel_country = t.hotel_country
 AND q.hotel_market = t.hotel_market

UNION ALL

SELECT
    q.row_id,
    t.hotel_cluster,
    6 AS source_priority,
    t.source_rank,
    t.score
FROM query_rows q
CROSS JOIN top_global t;

CREATE OR REPLACE TEMP TABLE final_candidates AS
WITH deduplicated AS (
    SELECT
        row_id,
        hotel_cluster,
        source_priority,
        source_rank,
        score
    FROM all_candidates
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY row_id, hotel_cluster
        ORDER BY source_priority, source_rank, score DESC
    ) = 1
)
SELECT
    row_id,
    hotel_cluster,
    source_priority,
    source_rank,
    score,
    ROW_NUMBER() OVER (
        PARTITION BY row_id
        ORDER BY source_priority, source_rank, score DESC, hotel_cluster
    ) AS final_rank
FROM deduplicated
QUALIFY final_rank <= 5;
"""


def _create_history(con: object, train_path: Path, cutoff: date | None) -> None:
    cutoff_filter = ""
    if cutoff is not None:
        cutoff_filter = f"WHERE date_time < DATE '{cutoff.isoformat()}'"

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW history AS
        SELECT
            *,
            POWER(
                GREATEST(1, DATE_DIFF('month', DATE '2012-12-01', CAST(date_time AS DATE))),
                2
            ) * (3.0 + 17.60 * is_booking) AS event_weight
        FROM read_parquet('{sql_path(train_path)}')
        {cutoff_filter}
        """
    )


def _create_validation_rows(con: object, train_path: Path, cutoff: date) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE query_rows AS
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY date_time, user_id, srch_destination_id, hotel_market, hotel_cluster
            ) - 1 AS row_id,
            *
        FROM read_parquet('{sql_path(train_path)}')
        WHERE date_time >= DATE '{cutoff.isoformat()}'
          AND is_booking = 1
        """
    )


def _create_test_rows(con: object, test_path: Path) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE query_rows AS
        SELECT id AS row_id, *
        FROM read_parquet('{sql_path(test_path)}')
        """
    )


def _build_candidates(con: object) -> None:
    print("[baseline] building top-cluster lookup tables")
    con.execute(TOP_TABLES_SQL)
    print("[baseline] joining and ranking candidates")
    con.execute(CANDIDATES_SQL)


def validate_baseline(
    paths: ProjectPaths,
    *,
    cutoff: date = date(2014, 8, 1),
    threads: int = 4,
    memory_limit: str = "8GB",
) -> BaselineMetrics:
    train_path = paths.processed_dir / "train.parquet"
    if not train_path.exists():
        raise FileNotFoundError("train.parquet is missing. Run the prepare command first.")

    paths.ensure_directories()
    database_path = paths.processed_dir / "stage1.duckdb"
    predictions_path = paths.artifacts_dir / "validation_predictions.csv"
    metrics_path = paths.artifacts_dir / "validation_metrics.json"

    con = connect(database_path, threads=threads, memory_limit=memory_limit)
    try:
        _create_history(con, train_path, cutoff)
        _create_validation_rows(con, train_path, cutoff)
        _build_candidates(con)

        history_rows = con.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        validation_rows = con.execute("SELECT COUNT(*) FROM query_rows").fetchone()[0]
        if validation_rows == 0:
            raise RuntimeError("The temporal validation split contains no booking rows.")

        candidate_recall = con.execute(
            """
            SELECT AVG(CASE WHEN f.hotel_cluster IS NULL THEN 0.0 ELSE 1.0 END)
            FROM query_rows q
            LEFT JOIN final_candidates f
              ON q.row_id = f.row_id
             AND q.hotel_cluster = f.hotel_cluster
            """
        ).fetchone()[0]
        map_at_5 = con.execute(
            """
            SELECT AVG(COALESCE(1.0 / f.final_rank, 0.0))
            FROM query_rows q
            LEFT JOIN final_candidates f
              ON q.row_id = f.row_id
             AND q.hotel_cluster = f.hotel_cluster
            """
        ).fetchone()[0]
        exact_geo_coverage = con.execute(
            """
            SELECT AVG(CASE WHEN matched.row_id IS NULL THEN 0.0 ELSE 1.0 END)
            FROM query_rows q
            LEFT JOIN (
                SELECT DISTINCT row_id FROM all_candidates WHERE source_priority = 1
            ) matched USING (row_id)
            """
        ).fetchone()[0]
        city_distance_coverage = con.execute(
            """
            SELECT AVG(CASE WHEN matched.row_id IS NULL THEN 0.0 ELSE 1.0 END)
            FROM query_rows q
            LEFT JOIN (
                SELECT DISTINCT row_id FROM all_candidates WHERE source_priority = 2
            ) matched USING (row_id)
            """
        ).fetchone()[0]

        con.execute(
            f"""
            COPY (
                SELECT
                    q.row_id,
                    q.hotel_cluster AS actual_hotel_cluster,
                    STRING_AGG(
                        CAST(f.hotel_cluster AS VARCHAR),
                        ' ' ORDER BY f.final_rank
                    ) AS predicted_hotel_clusters
                FROM query_rows q
                LEFT JOIN final_candidates f USING (row_id)
                GROUP BY q.row_id, q.hotel_cluster
                ORDER BY q.row_id
            ) TO '{sql_path(predictions_path)}' (HEADER, DELIMITER ',')
            """
        )

        metrics = BaselineMetrics(
            cutoff=cutoff.isoformat(),
            history_rows=history_rows,
            validation_rows=validation_rows,
            candidate_recall_at_5=float(candidate_recall),
            map_at_5=float(map_at_5),
            exact_geo_coverage=float(exact_geo_coverage),
            city_distance_coverage=float(city_distance_coverage),
        )
        metrics_path.write_text(
            json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        print(f"[baseline] predictions: {predictions_path}")
        print(f"[baseline] metrics: {metrics_path}")
        return metrics
    finally:
        con.close()


def build_submission(
    paths: ProjectPaths,
    *,
    threads: int = 4,
    memory_limit: str = "8GB",
) -> Path:
    train_path = paths.processed_dir / "train.parquet"
    test_path = paths.processed_dir / "test.parquet"
    if not train_path.exists() or not test_path.exists():
        raise FileNotFoundError("Processed train/test files are missing. Run prepare first.")

    paths.ensure_directories()
    database_path = paths.processed_dir / "stage1.duckdb"
    submission_path = paths.artifacts_dir / "submission_stage1.csv"

    con = connect(database_path, threads=threads, memory_limit=memory_limit)
    try:
        _create_history(con, train_path, cutoff=None)
        _create_test_rows(con, test_path)
        _build_candidates(con)
        con.execute(
            f"""
            COPY (
                SELECT
                    q.row_id AS id,
                    STRING_AGG(
                        CAST(f.hotel_cluster AS VARCHAR),
                        ' ' ORDER BY f.final_rank
                    ) AS hotel_cluster
                FROM query_rows q
                JOIN final_candidates f USING (row_id)
                GROUP BY q.row_id
                ORDER BY q.row_id
            ) TO '{sql_path(submission_path)}' (HEADER, DELIMITER ',')
            """
        )
        print(f"[baseline] submission: {submission_path}")
        return submission_path
    finally:
        con.close()
