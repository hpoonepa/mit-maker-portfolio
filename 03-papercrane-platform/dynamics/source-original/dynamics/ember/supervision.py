"""Label-only helpers; never imported by feature extraction or prediction."""

from __future__ import annotations

import random

import numpy as np

from .candidates import jaccard
from .schema import Reference, Site, Target


def site_overlap_targets(sites: list[Site], reference: Reference) -> np.ndarray:
    if not reference.valid:
        raise ValueError("Invalid reference cannot supervise ranking")
    return np.asarray(
        [
            max((jaccard(site.residues, ref.residues) for ref in reference.sites), default=0.0)
            for site in sites
        ],
        dtype=np.float32,
    )


def ranking_pairs(
    overlaps: np.ndarray,
    *,
    positive_min: float = 0.25,
    nonmatch_max_exclusive: float = 0.1,
    maximum_pairs: int = 256,
    seed: int = 1729,
) -> np.ndarray:
    values = np.asarray(overlaps, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("Overlap targets must be a finite vector in [0,1]")
    if not 0 <= nonmatch_max_exclusive < positive_min <= 1:
        raise ValueError("Pairing thresholds must leave an explicit ambiguity interval")
    if type(maximum_pairs) is not int or maximum_pairs < 1:
        raise ValueError("Maximum pair count must be positive")
    positive = np.flatnonzero(values >= positive_min)
    nonmatch = np.flatnonzero(values < nonmatch_max_exclusive)
    total = len(positive) * len(nonmatch)
    if not total:
        return np.empty((0, 2), dtype=np.int64)
    offsets = (
        range(total)
        if total <= maximum_pairs
        else sorted(random.Random(seed).sample(range(total), maximum_pairs))
    )
    return np.asarray(
        [(positive[offset // len(nonmatch)], nonmatch[offset % len(nonmatch)]) for offset in offsets],
        dtype=np.int64,
    )


def training_positive_weight(
    targets: list[Target], references: dict[str, Reference], *, maximum: float = 20.0
) -> float:
    """Protein-balanced prevalence; cap is an explicit development hyperparameter."""
    if maximum < 1 or not np.isfinite(maximum):
        raise ValueError("Maximum positive weight must be finite and at least one")
    prevalence = []
    for target in targets:
        if target.partition != "train":
            raise ValueError("Class weighting uses training targets only")
        ref = references[target.target_id]
        if not ref.valid or ref.residue_labels is None:
            raise ValueError("Training target lacks valid residue labels")
        labels = np.asarray(ref.residue_labels)
        mask = np.asarray(ref.residue_label_mask)
        if len(labels) != len(target.sequence):
            raise ValueError("Residue label length differs from target sequence")
        if mask.any():
            prevalence.append(float(labels[mask].mean()))
    if not prevalence or np.mean(prevalence) <= 0:
        raise ValueError("No positive training labels")
    p = float(np.mean(prevalence))
    return float(min(maximum, max(1.0, (1 - p) / p)))
