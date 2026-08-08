from __future__ import annotations

import json
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
    contract_path: Path
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
            contract_path=resolved / "config" / "analytics_contract.json",
            sql_dir=resolved / "sql" / "analytics",
        )

    def ensure_base_directories(self) -> None:
        for path in (
            self.analytics_dir,
            self.marts_dir,
            self.artifacts_dir,
            self.contract_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        """Legacy convenience path retained for compatibility with prototype code."""
        return self.analytics_dir / "expedia_analytics.duckdb"

    @property
    def train_path(self) -> Path:
        return self.processed_dir / "train.parquet"

    @property
    def test_path(self) -> Path:
        return self.processed_dir / "test.parquet"

    @property
    def destinations_path(self) -> Path:
        return self.processed_dir / "destinations.parquet"

    def ensure_output_directories(self) -> None:
        self.ensure_base_directories()

    def _find_raw(self, stem: str) -> Path:
        candidates = (
            self.raw_dir / f"{stem}.csv",
            self.raw_dir / f"{stem}.csv.gz",
        )
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Missing raw source {stem}.csv or {stem}.csv.gz in {self.raw_dir}"
        )

    def find_raw_train(self) -> Path:
        return self._find_raw("train")

    def find_raw_test(self) -> Path:
        return self._find_raw("test")

    def find_raw_destinations(self) -> Path:
        return self._find_raw("destinations")

    @property
    def latest_pointer_path(self) -> Path:
        return self.analytics_dir / "LATEST_BUILD.json"

    def resolve_latest_database(self) -> Path:
        if not self.latest_pointer_path.exists():
            raise FileNotFoundError(
                f"No successful analytics build pointer: {self.latest_pointer_path}"
            )
        payload = json.loads(self.latest_pointer_path.read_text(encoding="utf-8"))
        database = Path(payload["database"])
        if not database.is_absolute():
            database = self.root / database
        if not database.exists():
            raise FileNotFoundError(f"Latest analytics database is missing: {database}")
        return database


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
