"""eval_metrics.py — Pure-math retrieval metrics for the LOTO eval harness.

All functions operate on ranked lists of design IDs and sets of known positives.
No feature-table dependency; stdlib only.
"""

from __future__ import annotations

import math
from typing import Sequence, Set


def fold_adaptive_k(n_pos: int, default_k: int = 20) -> int:
    """Return an effective k that never exceeds the number of positives in a fold.

    Stabilises Precision@k on small folds: if a fold has only 3 positives,
    asking for Precision@20 is meaningless.  We cap k at n_pos (floored at 1
    so we never return 0).

    Args:
        n_pos:     Number of positive (hit) designs in the current fold.
        default_k: The nominal k to use when n_pos is large enough.

    Returns:
        Effective k = min(default_k, max(1, n_pos)).
    """
    return min(default_k, max(1, n_pos))


def precision_at_k(
    ranked_design_ids: Sequence[str],
    positive_ids: Set[str],
    k: int,
) -> float:
    """Precision at rank k for a single target.

    Computes the fraction of the top-k (or top-n if n < k) ranked designs
    that are true positives.

    Args:
        ranked_design_ids: Ordered list of design IDs, best first.
        positive_ids:      Set of IDs that are known binders / hits.
        k:                 Nominal cut-off rank (must be > 0).

    Returns:
        Fraction of the effective-top-k that appear in positive_ids.
        Returns 0.0 if the ranking is empty.

    Raises:
        ValueError: If k <= 0.
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")

    n = len(ranked_design_ids)
    if n == 0:
        return 0.0

    effective_k = min(k, n)
    top_k = ranked_design_ids[:effective_k]
    hits = sum(1 for design_id in top_k if design_id in positive_ids)
    return hits / effective_k


def recall_at_budget(
    ranked_design_ids: Sequence[str],
    positive_ids: Set[str],
    budget: int,
) -> float:
    """Recall achieved when wet-lab capacity is limited to `budget` designs.

    Computes the fraction of all known positives that appear within the first
    `budget` entries of the ranked list.

    Args:
        ranked_design_ids: Ordered list of design IDs, best first.
        positive_ids:      Set of IDs that are known binders / hits.
        budget:            Maximum number of designs a lab could test.

    Returns:
        hits_in_budget / total_positives, capped at 1.0.
        Returns float("nan") when positive_ids is empty (undefined recall).
    """
    total = len(positive_ids)
    if total == 0:
        return float("nan")

    effective_budget = min(budget, len(ranked_design_ids))
    top = ranked_design_ids[:effective_budget]
    hits = sum(1 for design_id in top if design_id in positive_ids)
    return min(hits / total, 1.0)
