"""JSON-backed campaign state for the sequential Nebius runner.
Format-compatible with vast/resume.py (same field names) so that CLI can inspect it.
"""
from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CampaignState:
    campaign_id: str
    image: str
    total_seeds: int
    completed_seeds: list[int] = field(default_factory=list)
    failed_seeds: list[int] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    started_at: str = field(default_factory=_now)
    last_checkpoint: str = field(default_factory=_now)

    def pending_seeds(self, all_seeds: list[int]) -> list[int]:
        done = set(self.completed_seeds) | set(self.failed_seeds)
        return [s for s in all_seeds if s not in done]

    def record_success(self, seed: int, csv_line: str, output_dir: str) -> None:
        if seed not in self.completed_seeds:
            self.completed_seeds.append(seed)
        self.results.append({"seed": seed, "csv_line": csv_line, "output_dir": output_dir})

    def record_failure(self, seed: int, error: str) -> None:
        if seed not in self.failed_seeds:
            self.failed_seeds.append(seed)
        self.results.append({"seed": seed, "error": error})

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.last_checkpoint = _now()
        # Atomic write: temp file in same dir, then rename.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(self), f, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @classmethod
    def load(cls, path: str | Path) -> "CampaignState | None":
        path = Path(path)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return cls(**data)
