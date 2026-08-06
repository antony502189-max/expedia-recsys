from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AnalyticsPaths:
    root: Path
    raw_dir: Path
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
            raw_dir=resolved / "data" / "raw",
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

    def find_raw_train(self) -> Path:
        return self._find_raw(("train.csv", "train.csv.gz"))

    def find_raw_destinations(self) -> Path:
        return self._find_raw(("destinations.csv", "destinations.csv.gz"))

    def _find_raw(self, names: tuple[str, ...]) -> Path:
        for name in names:
            candidate = self.raw_dir / name
            if candidate.exists():
                return candidate
        expected = ", ".join(names)
        raise FileNotFoundError(f"No raw source in {self.raw_dir}; expected one of: {expected}")

    def ensure_output_directories(self) -> None:
        self.analytics_dir.mkdir(parents=True, exist_ok=True)
        self.marts_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
