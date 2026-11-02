# SPDX-License-Identifier: MIT
"""Pure metric functions for the hotspot-preflight benchmark.

Two metric families, because the two stages of the tool fail in different ways
(spec section 4.1). Reporting only one would hide a real weakness:

* **Prediction metrics** — how good is the ranking of candidate sites?
  :func:`per_residue_auroc`, :func:`per_residue_auprc`,
  :func:`top_k_patch_recall`, plus the ported retrieval metrics
  :func:`precision_at_k` and :func:`recall_at_budget`.
* **Filter metrics** — a filter's cardinal sin is rejecting a site that was
  fine, so :func:`false_rejection_rate` is the primary number for the reality
  layer and it should sit near zero.

Every function here is pure: no file access, no network, no global state, no
RNG. That is deliberate — the statistics must be testable without a benchmark
on disk, and the headline number must not depend on I/O ordering.

Provenance
----------
``fold_adaptive_k``, ``precision_at_k`` and ``recall_at_budget`` are ported
verbatim in behaviour (docstrings rewritten for this domain) from
``scorer/eval_metrics.py`` in the Paper Crane ``binder-scorer`` tree, where
they ship with their own test suite. They are reused rather than rewritten so
that a number produced here is comparable to a number produced there.
"""

from __future__ import annotations

import math
from typing import Collection, Iterable, Sequence

import numpy as np
from scipy import stats

__all__ = [
    "fold_adaptive_k",
    "precision_at_k",
    "recall_at_budget",
    "false_rejection_rate",
    "per_residue_auroc",
    "per_residue_auprc",
    "top_k_patch_recall",
    "patch_epitope_overlap",
    "patch_precision_at_k",
    "union_coverage_at_k",
    "strict_containment_achievable",
    "assert_key_spaces_overlap",
    "DisjointKeySpaces",
    "DEFAULT_MIN_COVERAGE",
]

# A proposed patch "finds" the true epitope when it contains at least this
# fraction of the observed epitope residues. There is no community standard for
# this; 0.5 is our stated choice, and it is a keyword argument everywhere so a
# reader who disagrees can re-run with their own threshold rather than argue.
DEFAULT_MIN_COVERAGE: float = 0.5


# ---------------------------------------------------------------------------
# Ported retrieval metrics (binder-scorer / scorer/eval_metrics.py)
# ---------------------------------------------------------------------------
def fold_adaptive_k(n_pos: int, default_k: int = 20) -> int:
    """Return an effective k that never exceeds the number of positives.

    Stabilises precision on small folds: if a cluster contributes only three
    positive instances, asking for precision@20 is meaningless. k is capped at
    ``n_pos``, floored at 1 so the result is never 0 (which would make
    :func:`precision_at_k` raise).

    Ported from ``scorer/eval_metrics.py`` (binder-scorer).
    """
    return min(default_k, max(1, n_pos))


def precision_at_k(
    ranked_ids: Sequence[str],
    positive_ids: Collection[str],
    k: int,
) -> float:
    """Fraction of the top-k ranked items that are true positives.

    When the ranking is shorter than ``k`` the effective cut-off is the length
    of the ranking, so a short ranking is not penalised for being short — it is
    scored on what it actually proposed.

    Args:
        ranked_ids: ordered ids, best first.
        positive_ids: ids that are true positives.
        k: nominal cut-off rank, must be positive.

    Returns:
        hits / effective_k, or 0.0 for an empty ranking.

    Raises:
        ValueError: if ``k <= 0``.

    Ported from ``scorer/eval_metrics.py`` (binder-scorer).
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")

    n = len(ranked_ids)
    if n == 0:
        return 0.0

    effective_k = min(k, n)
    positives = set(positive_ids)
    hits = sum(1 for item in ranked_ids[:effective_k] if item in positives)
    return hits / effective_k


def recall_at_budget(
    ranked_ids: Sequence[str],
    positive_ids: Collection[str],
    budget: int,
) -> float:
    """Recall achieved when only ``budget`` items can be followed up.

    The budget framing is the honest one for this tool: a lab does not inspect
    a whole ranking, it inspects the few sites it can afford to build.

    Returns:
        hits_within_budget / total_positives, capped at 1.0. Returns NaN when
        there are no positives, because recall is undefined then — NaN
        propagates loudly instead of a 0.0 that would silently drag an average
        down.

    Ported from ``scorer/eval_metrics.py`` (binder-scorer).
    """
    positives = set(positive_ids)
    total = len(positives)
    if total == 0:
        return float("nan")

    effective_budget = min(budget, len(ranked_ids))
    hits = sum(1 for item in ranked_ids[:effective_budget] if item in positives)
    return min(hits / total, 1.0)


# ---------------------------------------------------------------------------
# Filter metrics
# ---------------------------------------------------------------------------
def false_rejection_rate(
    predicted_kills: Iterable[str],
    true_epitopes: Collection[str],
) -> float:
    """Fraction of experimentally observed epitope residues the filter KILLs.

    This is the primary filter metric. The reality layer exists to stop people
    designing against sites that are not real; every residue it kills that a
    crystallographer has actually seen an antibody touch is a bug, not a
    rounding error. Each one is meant to be triaged individually rather than
    averaged away, which is why this returns a rate per instance and the
    caller aggregates by cluster.

    Only killed residues in the observed epitope count toward this error.
    The suitability of other surface residues remains unknown.

    Args:
        predicted_kills: residue keys the filter returned a KILL verdict for.
        true_epitopes: residue keys observed in contact with the antibody.

    Returns:
        0.0 when nothing in the epitope was killed, 1.0 when all of it was.

    Raises:
        ValueError: if ``true_epitopes`` is empty, because the rate has no
            denominator and a 0.0 would read as a perfect score.
    """
    epitope = set(true_epitopes)
    if not epitope:
        raise ValueError(
            "false_rejection_rate needs at least one observed epitope residue; "
            "got an empty epitope, so the rate has no denominator. Drop the "
            "instance from the benchmark and log it instead of scoring it."
        )
    killed = set(predicted_kills)
    return len(killed & epitope) / len(epitope)


# ---------------------------------------------------------------------------
# Per-residue ranking metrics
# ---------------------------------------------------------------------------
def _check_binary_problem(
    scores: Sequence[float], labels: Sequence[bool]
) -> tuple[np.ndarray, np.ndarray]:
    """Validate and coerce a per-residue scoring problem.

    Raises rather than returning a sentinel: a single-class antigen (every
    residue an epitope residue, or none of them) has an undefined AUROC, and
    returning 0.5 there would quietly mix an undefined value into a mean.
    """
    if len(scores) != len(labels):
        raise ValueError(
            f"scores and labels must be the same length, got "
            f"{len(scores)} and {len(labels)}"
        )
    if len(scores) == 0:
        raise ValueError("cannot score an empty residue list")

    score_arr = np.asarray(scores, dtype=float)
    label_arr = np.asarray(labels, dtype=bool)

    if not np.all(np.isfinite(score_arr)):
        raise ValueError(
            "scores contain NaN or inf; a non-finite score has no rank, so "
            "impute or drop it upstream where the reason can be logged"
        )

    n_pos = int(label_arr.sum())
    if n_pos == 0 or n_pos == len(label_arr):
        raise ValueError(
            f"need both epitope and non-epitope residues to rank; got "
            f"{n_pos} positives out of {len(label_arr)}"
        )
    return score_arr, label_arr


def per_residue_auroc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """AUROC over residues of one antigen, higher score meaning more epitope-like.

    Computed from mid-ranks (the Mann-Whitney U identity) rather than by
    integrating a sampled ROC curve, so tied scores are handled exactly. Ties
    matter here: a SASA-derived score produces many identical values for fully
    buried residues, and a tie-blind implementation would score them as a
    lucky or unlucky ordering.
    """
    score_arr, label_arr = _check_binary_problem(scores, labels)
    n_pos = int(label_arr.sum())
    n_neg = len(label_arr) - n_pos

    ranks = stats.rankdata(score_arr)  # average ranks for ties
    rank_sum_pos = float(ranks[label_arr].sum())
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def per_residue_auprc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Average precision over residues of one antigen.

    AUPRC rather than AUROC alone because the epitope is a small minority of
    the surface (median epitope 17 residues against a whole antigen), and
    AUROC is optimistic under that imbalance.

    This is the step-wise average-precision estimator (the sum of precision at
    each positive, divided by the number of positives), not a trapezoidal
    integration of the interpolated curve — trapezoid interpolation is
    optimistically biased. Tied scores are broken by a stable sort, matching
    the usual ``average_precision_score`` behaviour; with heavy ties prefer
    :func:`per_residue_auroc`, which is exact under ties.
    """
    score_arr, label_arr = _check_binary_problem(scores, labels)
    n_pos = int(label_arr.sum())

    order = np.argsort(-score_arr, kind="stable")
    hits = label_arr[order]
    cumulative_hits = np.cumsum(hits)
    precision = cumulative_hits / np.arange(1, len(hits) + 1)
    return float(precision[hits].sum() / n_pos)


def top_k_patch_recall(
    ranked_patches: Sequence[Collection[str]],
    true_epitope: Collection[str],
    k: int,
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> float:
    """Is the true epitope among the top ``k`` proposed patches?

    A hit-or-miss indicator for one antigen (1.0 or 0.0); averaging it over the
    benchmark gives the top-k patch recall reported in spec section 4.1. A
    patch counts as finding the epitope when it contains at least
    ``min_coverage`` of the observed epitope residues — a patch that clips one
    corner of the epitope has not found it, and requiring exact set equality
    would make the metric unmeasurable.

    Args:
        ranked_patches: proposed patches, best first; each a collection of
            residue keys.
        true_epitope: observed epitope residue keys.
        k: how many of the top patches the user is assumed to look at.
        min_coverage: fraction of the epitope a patch must contain, in (0, 1].

    Raises:
        ValueError: if ``k <= 0``, ``true_epitope`` is empty, or
            ``min_coverage`` is outside (0, 1].
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")
    if not 0.0 < min_coverage <= 1.0:
        raise ValueError(
            f"min_coverage must be in (0, 1], got {min_coverage}"
        )
    epitope = set(true_epitope)
    if not epitope:
        raise ValueError(
            "top_k_patch_recall needs a non-empty true epitope; an instance "
            "with no observed epitope must be dropped and logged"
        )
    if not ranked_patches:
        return 0.0

    needed = math.ceil(min_coverage * len(epitope))
    for patch in ranked_patches[: min(k, len(ranked_patches))]:
        if len(set(patch) & epitope) >= needed:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Scale-appropriate patch metrics
# ---------------------------------------------------------------------------
# The benchmark's labels are ANTIBODY epitopes (median 20 residues) while
# ``surface.enumerate_patches`` sizes patches for a MINIBINDER interface
# (PATCH_MAX_RESIDUES = 12, deliberately). An antibody epitope is therefore
# roughly two patches, and :func:`top_k_patch_recall` — which asks whether one
# patch *contains* half an epitope — is asking the wrong question at this
# scale. It is kept unchanged and still reported, because lowering
# ``min_coverage`` until the number improves would be tuning. These three sit
# beside it and ask questions the units support.
def patch_epitope_overlap(
    ranked_patches: Sequence[Collection[str]],
    true_epitope: Collection[str],
    k: int,
) -> float:
    """Does any of the top ``k`` patches touch the epitope at all (>=1 residue)?

    The weakest useful question, and therefore the floor: a predictor that
    cannot clear this is not finding the site in any sense. It also makes a
    join failure obvious — random 12-residue patches on a 250-residue antigen
    hit a 20-residue epitope regularly, so an *exactly* zero overlap rate is
    evidence of disjoint key spaces rather than of a weak predictor.
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")
    epitope = set(true_epitope)
    if not epitope:
        raise ValueError("patch_epitope_overlap needs a non-empty true epitope")
    for patch in ranked_patches[: min(k, len(ranked_patches))]:
        if set(patch) & epitope:
            return 1.0
    return 0.0


def patch_precision_at_k(
    ranked_patches: Sequence[Collection[str]],
    true_epitope: Collection[str],
    k: int,
) -> float:
    """Best purity among the top ``k`` patches: is a patch *on* the epitope?

    Purity is the fraction of a patch's own residues that are epitope
    residues. This is the question that matches the units — "is this proposal
    sitting on the site" rather than "does this proposal contain the whole
    site" — and it is well defined however much larger the epitope is than a
    patch. The best patch among the top k is taken rather than the mean, so
    the number answers "did the method put *a* good patch in front of the
    user", which is what a user triaging k sites experiences.
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")
    epitope = set(true_epitope)
    if not epitope:
        raise ValueError("patch_precision_at_k needs a non-empty true epitope")
    if not ranked_patches:
        return 0.0
    best = 0.0
    for patch in ranked_patches[: min(k, len(ranked_patches))]:
        residues = set(patch)
        if residues:
            best = max(best, len(residues & epitope) / len(residues))
    return best


def union_coverage_at_k(
    ranked_patches: Sequence[Collection[str]],
    true_epitope: Collection[str],
    k: int,
) -> float:
    """Fraction of the epitope covered by the UNION of the top ``k`` patches.

    If an antibody epitope spans about two minibinder-sized patches, the
    top-k union is the honest way to ask whether the method found the site:
    it allows the epitope to be assembled from neighbouring proposals, which
    is how a user would actually read a ranked patch list, while still
    penalising a method whose top k sit somewhere else entirely.
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")
    epitope = set(true_epitope)
    if not epitope:
        raise ValueError("union_coverage_at_k needs a non-empty true epitope")
    if not ranked_patches:
        return 0.0
    covered: set[str] = set()
    for patch in ranked_patches[: min(k, len(ranked_patches))]:
        covered |= set(patch)
    return len(covered & epitope) / len(epitope)


def strict_containment_achievable(
    epitope_size: int,
    patch_max_residues: int,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> bool:
    """Can :func:`top_k_patch_recall` fire at all for this epitope size?

    A hit needs ``ceil(min_coverage * epitope_size)`` epitope residues inside a
    single patch, and a patch holds at most ``patch_max_residues``. When the
    first exceeds the second the metric is arithmetically incapable of
    returning 1.0 no matter how good the predictor is, and a 0.0 it reports
    means "could not fire", not "failed". Callers use this to say which of
    those two a zero is.
    """
    if epitope_size <= 0 or patch_max_residues <= 0:
        raise ValueError(
            f"epitope_size and patch_max_residues must be positive, got "
            f"{epitope_size} and {patch_max_residues}"
        )
    return math.ceil(min_coverage * epitope_size) <= patch_max_residues


class DisjointKeySpaces(ValueError):
    """The predictor's residue keys and the epitope's keys never intersect.

    Raised rather than allowed to produce a zero. A metric comparing two
    disjoint key spaces reports 0.0000 on every instance regardless of the
    predictor, which is indistinguishable from a real failure — and this
    project exists to catch exactly that class of silent format mismatch.
    """


def assert_key_spaces_overlap(
    predicted_keys: Collection[str],
    epitope_keys: Collection[str],
    *,
    context: str = "",
) -> None:
    """Fail loudly when two residue-key spaces cannot intersect.

    Called once per run over the pooled keys, not per instance: a single
    antigen legitimately has patches that miss its epitope, but across a whole
    benchmark the two key spaces must overlap somewhere.

    Raises:
        DisjointKeySpaces: naming both formats with an example from each, so
            the fix is a one-line normalisation rather than a hunt.
    """
    predicted = set(predicted_keys)
    epitope = set(epitope_keys)
    if not predicted or not epitope:
        raise DisjointKeySpaces(
            f"{context}: one key space is empty (predicted {len(predicted)}, "
            f"epitope {len(epitope)}), so no metric can fire"
        )
    if predicted & epitope:
        return
    raise DisjointKeySpaces(
        f"{context}: the predictor's residue keys and the epitope's residue "
        f"keys never intersect, so every patch metric is exactly 0.0000 by "
        f"construction and independent of the predictor. Example predicted "
        f"key {sorted(predicted)[0]!r}; example epitope key "
        f"{sorted(epitope)[0]!r}. Normalise both to one canonical form "
        f"(str(ResidueKey), e.g. 'A115') at the loading boundary."
    )
