"""Parse a pinned Lacuna report without importing or running Lacuna.

Use a normalized single-chain detector input and its explicit reverse map.
The native report includes the input apo model in n_conformers. Its rank, not
druggability/crypticity, determines the native learned-ranker ordering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..io import content_hash, file_hash, read_json
from ..schema import Prediction, RankedSite, ResidueID, Target, finite, require_indices


@dataclass(frozen=True)
class LacunaReport:
    report_sha256: str
    n_conformers_including_apo: int
    ranked_by: str
    sites: tuple[RankedSite, ...]


def parse_report(path: str | Path, residue_mapping: dict[ResidueID, int]) -> LacunaReport:
    report = read_json(path)
    required = {"protein", "n_conformers", "ranked_by", "n_pockets_found", "n_cryptic_pockets", "pockets"}
    if set(report) != required or type(report["n_conformers"]) is not int or report["n_conformers"] < 1:
        raise ValueError("Unsupported Lacuna report schema/frame count")
    if report["ranked_by"] not in {
        "learned",
        "learned-plm",
        "crypticity",
        "druggability",
        "persistence",
        "balanced",
    }:
        raise ValueError("Unknown native Lacuna ranker")
    if type(report["n_pockets_found"]) is not int or report["n_pockets_found"] != len(report["pockets"]):
        raise ValueError("Lacuna report pocket count mismatch")
    sites, ranks = [], set()
    for pocket in report["pockets"]:
        rank = pocket["rank"]
        if type(rank) is not int or rank < 1 or rank in ranks:
            raise ValueError("Duplicate/invalid Lacuna rank")
        ranks.add(rank)
        frames = pocket["appears_in_conformers"]
        if (
            not frames
            or len(set(frames)) != len(frames)
            or any(type(i) is not int or not 0 <= i < report["n_conformers"] for i in frames)
        ):
            raise ValueError("Invalid Lacuna support-frame indices")
        center = pocket["centroid"]
        if len(center) != 3:
            raise ValueError("Invalid Lacuna centroid")
        for coordinate in center:
            finite(coordinate, "Lacuna centroid coordinate")
        residues = []
        for label in pocket["lining_residues"]:
            match = re.fullmatch(r"([A-Z]{3})(-?\d+):([^:]*)", label)
            if match is None:
                raise ValueError("Unsupported Lacuna residue label; use normalized detector numbering")
            author = ResidueID(match[3], int(match[2]))
            if author not in residue_mapping:
                raise ValueError(f"Lacuna residue outside declared input mapping: {label}")
            residues.append(residue_mapping[author])
        sites.append(
            RankedSite(
                f"lacuna-rank-{rank:06d}",
                tuple(sorted(set(residues))),
                -float(rank),
                "ensemble" if any(i > 0 for i in frames) else "apo",
            )
        )
    return LacunaReport(
        file_hash(path),
        report["n_conformers"],
        report["ranked_by"],
        tuple(sorted(sites, key=lambda s: -s.score)),
    )


def native_prediction(
    target: Target,
    report: LacunaReport,
    *,
    method_sha256: str,
    run_receipt: dict,
    requested_generated_frames: int,
    top_k: int = 5,
    runtime_seconds: float | None = None,
    cost_usd: float | None = None,
) -> Prediction:
    from ..candidates import ranked_unique

    expected = {
        "backend": "nma",
        "detector": "alpha",
        "ranked_by": report.ranked_by,
        "report_sha256": report.report_sha256,
        "input_target_sha256": content_hash(target),
        "method_sha256": method_sha256,
    }
    if any(run_receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("Lacuna run receipt does not bind the declared NMA/alpha method and input")

    for site in report.sites:
        require_indices(site.residues, "Lacuna site residues", len(target.sequence))
    native_frames = report.n_conformers_including_apo - 1
    if type(requested_generated_frames) is not int or not 0 <= native_frames <= requested_generated_frames:
        raise ValueError("Requested/native Lacuna conformer counts disagree")
    selected = tuple(ranked_unique(report.sites, top_k=top_k))
    return Prediction(
        target.target_id,
        "lacuna-nma-alpha-" + report.ranked_by,
        "ok" if selected else "no_candidates",
        selected,
        content_hash(target),
        method_sha256,
        requested_generated_frames,
        native_frames,
        runtime_seconds,
        cost_usd,
        warnings=(
            "Rank score is negative native rank. Native reported frames are not an all-atom quality certification.",
            "The JSON report does not prove the backend/input/checkpoint used; bind the independent run receipt.",
            "n_pockets_found counts reported pockets; a truncated report cannot establish complete proposal coverage.",
        ),
    )
