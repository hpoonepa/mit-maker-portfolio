"""Shared paths for research scripts; large generated data stays outside source."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("PRINCE_DATA_DIR", str(REPO / "work"))).expanduser().resolve()
MODEL = REPO / "src/prince_ranker/data/site_ranker.json"
