from __future__ import annotations

from typing import Mapping, TypedDict


class ScoredDesignDict(TypedDict):
    """Dict-based scored design row (eval/baseline layer).
    Named ScoredDesignDict to avoid collision with any scorer.types.ScoredDesign dataclass."""
    design_id: str
    score: float
    rank: int


# Alias for code importing ScoredDesign from eval_types
ScoredDesign = ScoredDesignDict

# CANONICAL scoring-metric keys — aligned to columns ACTUALLY present in
# data/processed/labeled_features.csv. All computational__-prefixed.
# (ipsae_min_native, shape_complementarity, rmsd_binder are also metrics but
#  are not computational__-prefixed in the current ETL; the baseline/eval tasks
#  handle those + the best-available-ipSAE fallback explicitly.)
NUMERIC_METRIC_KEYS: tuple[str, ...] = (
    "computational__boltz2_min_ipsae",
    "computational__boltz2_iptm",
    "computational__boltz2_lis",
    "computational__actifptm",
    "computational__interface_residues",
    "computational__boltz2_complex_iplddt",
    "computational__proteinmpnn_score",
    "computational__esmfold_plddt",
)

# Substrings whose metrics are lower-is-better (inverted when used as a score).
ENSEMBLE_INVERT_SUBSTRINGS: tuple[str, ...] = (
    "pae", "rmsd", "clash", "energy", "ipae", "i_pae",
)


def make_scored_design(design_id: str, score: float, rank: int) -> ScoredDesignDict:
    return {"design_id": design_id, "score": float(score), "rank": int(rank)}


def is_real_binder(label_row: Mapping[str, object]) -> bool:
    """A confirmed REAL binder iff binds is literally True (wet-lab yes)."""
    return label_row.get("binds") is True
