"""Read P2Rank's native CSV output using explicit canonical residue mapping.

Schema checked against upstream 369c64e0d368b88c2b2c8a7386af77bc87af92e5
misc/visualization/predict_1fbl/1fbl.pdb_predictions.csv. No Java/tool execution.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from ..mapping import parse_author_selection
from ..schema import ResidueID


@dataclass(frozen=True)
class P2RankSite:
    name: str
    rank: int
    score: float
    reported_probability: float
    residues: tuple[int, ...]
    center: tuple[float, float, float]


def parse_predictions(path: str | Path, residue_mapping: dict[ResidueID, int]) -> list[P2RankSite]:
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        if reader.fieldnames is None:
            raise ValueError("Empty P2Rank output without header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        required = {"name", "rank", "score", "probability", "center_x", "center_y", "center_z", "residue_ids"}
        if not required <= set(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("P2Rank CSV header mismatch")
        sites = []
        for row in reader:
            if None in row or any(row[key] is None for key in required):
                raise ValueError("Malformed P2Rank CSV row")
            residues = []
            for value in row["residue_ids"].split():
                author = parse_author_selection(value)
                if author not in residue_mapping:
                    raise ValueError(f"P2Rank residue outside canonical mapping: {value}")
                residues.append(residue_mapping[author])
            score = float(row["score"])
            probability = float(row["probability"])
            center = tuple(float(row["center_" + axis]) for axis in "xyz")
            rank = int(row["rank"])
            if (
                not residues
                or rank < 1
                or not row["name"].strip()
                or not all(math.isfinite(x) for x in (score, probability, *center))
                or not 0 <= probability <= 1
            ):
                raise ValueError("Invalid P2Rank site record")
            sites.append(
                P2RankSite(
                    row["name"].strip(), rank, score, probability, tuple(sorted(set(residues))), center
                )
            )
    if len({s.name for s in sites}) != len(sites) or len({s.rank for s in sites}) != len(sites):
        raise ValueError("Duplicate P2Rank names/ranks")
    return sorted(sites, key=lambda site: site.rank)
