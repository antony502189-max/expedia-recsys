from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AnalyticsPaths:
    root: Path
    processed_dir: Path
    analytics_dir: Path
    marts_dir: Path
    artifacts_dir: Path
    sql_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> AnalyticsPaths:
        resolved = root.resolve()
        return cls(
            root=resolved,
            processed_dir=resolved / "data" / "processed",
            analytics_dir=resolved / "data" / "analytics",
            marts_dir=resolved / "data" / "marts",
            artifacts_dir=resolved / "artifacts" / "analytics",
            sql_dir=resolved / "sql" / "analytics",
        )

    @property
    def database_path(self) -> Path:
        return self.analytics_dir / "expedia_analytics.duckdb"

    @property
    def train_path(self) -> Path:
        return self.processed_dir / "train.parquet"

    @property
    def destinations_path(self) -> Path:
        return self.processed_dir / "destinations.parquet"

    def ensure_output_directories(self) -> None:
        self.analytics_dir.mkdir(parents=True, exist_ok=True)
        self.marts_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
