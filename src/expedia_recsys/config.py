from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path
    raw_dir: Path
    processed_dir: Path
    artifacts_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> ProjectPaths:
        root = root.resolve()
        return cls(
            root=root,
            raw_dir=root / "data" / "raw",
            processed_dir=root / "data" / "processed",
            artifacts_dir=root / "artifacts",
        )

    def ensure_directories(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
