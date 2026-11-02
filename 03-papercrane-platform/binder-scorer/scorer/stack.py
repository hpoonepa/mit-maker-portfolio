"""stack.py — B_STACK: a leakage-safe blend of the LLM prior and the data model.

Motivation (see docs/research/2026-06-29-research-eval-publishability.md): B_LLM
ties B0 and B6 ties B0, but neither dominates — the textbook signature that a
*fit* convex blend of the two can beat both. B_STACK ranks each test design by::

    final = lambda * z(B_LLM_score) + (1 - lambda) * z(B6_score)

where each arm's raw scores are z-normalized within the test fold and ``lambda``
is chosen by NESTED leave-one-train-target-out — the held-out target never enters
selection. Because ``lambda in {0, .25, .5, .75, 1}`` includes both endpoints, the
stack cannot (asymptotically) do worse than the better single arm.

Leakage discipline: the outer harness already holds target T out; here we further
hold each TRAIN target out to pick lambda, so T's designs are untouched by both
arm-training and lambda-selection. Pure-blend helpers (``_zscore``, ``_blend``,
``select_lambda``) are import-free and unit-tested in isolation; the base arms are
injected (default = the real B_LLM / B6) so tests need no LightGBM or live priors.
"""

from __future__ import annotations

import math
from statistics import fmean
from typing import Callable, Sequence

from scorer.eval_metrics import fold_adaptive_k, precision_at_k
from scorer.eval_types import ScoredDesignDict, is_real_binder
from scorer.loto_split import well_powered_targets

DEFAULT_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
# Used only when a fold has NO well-powered train target to select lambda on:
# an even blend is the least-committal prior.
DEFAULT_LAMBDA: float = 0.5


# --------------------------------------------------------------------------- #
# Pure blend helpers (no I/O, no model training)
# --------------------------------------------------------------------------- #
def _zscore(scores: Sequence[float]) -> list[float]:
    """Z-normalize, NaN-safe. Missing values -> 0 (neutral). All-equal -> zeros.

    Mean/std are computed over the finite values only; a NaN entry contributes
    0.0 to the blend rather than poisoning the sum.
    """
    finite = [s for s in scores if isinstance(s, (int, float)) and math.isfinite(s)]
    if not finite:
        return [0.0] * len(scores)
    mu = fmean(finite)
    var = fmean([(s - mu) ** 2 for s in finite])
    sd = math.sqrt(var)
    if sd == 0.0:
        return [0.0] * len(scores)
    out: list[float] = []
    for s in scores:
        if isinstance(s, (int, float)) and math.isfinite(s):
            out.append((s - mu) / sd)
        else:
            out.append(0.0)
    return out


def _blend(z_llm: Sequence[float], z_b6: Sequence[float], lam: float) -> list[float]:
    """Convex combination ``lam*z_llm + (1-lam)*z_b6`` (element-wise)."""
    return [lam * a + (1.0 - lam) * b for a, b in zip(z_llm, z_b6)]


def _precision_for_lambda(fold: dict, lam: float) -> float:
    """Rank one inner fold by the blended score at ``lam`` and score Precision@k."""
    blended = _blend(fold["z_llm"], fold["z_b6"], lam)
    pairs = list(zip(fold["ids"], blended))
    ranked = [did for did, _ in sorted(pairs, key=lambda p: (-p[1], p[0]))]
    return precision_at_k(ranked, fold["pos_ids"], fold["k"])


def select_lambda(inner_folds: Sequence[dict], grid: Sequence[float]) -> float:
    """Pick the lambda maximizing mean inner Precision@k.

    ``inner_folds`` items each carry precomputed ``z_llm``/``z_b6`` arrays,
    ``ids`` (aligned), ``pos_ids`` (set), and ``k``. Ties are broken toward the
    most balanced blend (smallest ``|lambda - 0.5|``), then the smaller lambda —
    a deterministic rule that gives the blend a fair shot over either endpoint.
    """
    if not inner_folds:
        return DEFAULT_LAMBDA
    best_lam: float | None = None
    best_score = float("-inf")
    for lam in grid:
        m = fmean([_precision_for_lambda(f, lam) for f in inner_folds])
        if m > best_score or (
            m == best_score
            and best_lam is not None
            and (abs(lam - 0.5), lam) < (abs(best_lam - 0.5), best_lam)
        ):
            best_score, best_lam = m, lam
    return best_lam if best_lam is not None else DEFAULT_LAMBDA


# --------------------------------------------------------------------------- #
# Arm plumbing
# --------------------------------------------------------------------------- #
def _arm_scores(fn: Callable, train_labels, train, test) -> list[float]:
    """Run an arm scorer and return its raw scores aligned to ``test`` order."""
    by_id = {s["design_id"]: s["score"] for s in fn(train_labels, train, test)}
    return [by_id.get(d["design_id"], float("nan")) for d in test]


def _inner_folds(train_designs, llm_fn, b6_fn) -> list[dict]:
    """Build the nested-LOTO inner folds over well-powered TRAIN targets."""
    wp = well_powered_targets(train_designs)
    folds: list[dict] = []
    for u in sorted(wp):
        inner_train = [d for d in train_designs if d["target"] != u]
        inner_test = [d for d in train_designs if d["target"] == u]
        inner_labels = [is_real_binder(d) for d in inner_train]
        z_llm = _zscore(_arm_scores(llm_fn, inner_labels, inner_train, inner_test))
        z_b6 = _zscore(_arm_scores(b6_fn, inner_labels, inner_train, inner_test))
        pos_ids = {d["design_id"] for d in inner_test if is_real_binder(d)}
        folds.append({
            "z_llm": z_llm,
            "z_b6": z_b6,
            "ids": [d["design_id"] for d in inner_test],
            "pos_ids": pos_ids,
            "k": fold_adaptive_k(len(pos_ids)),
        })
    return folds


def b_stack(
    train_labels,
    train_designs,
    test_designs,
    *,
    llm_fn: Callable | None = None,
    b6_fn: Callable | None = None,
    grid: Sequence[float] = DEFAULT_GRID,
) -> list[ScoredDesignDict]:
    """Rank test designs by a nested-LOTO-selected convex blend of B_LLM and B6.

    ``llm_fn`` / ``b6_fn`` default to the real B_LLM / B6 scorers (imported
    lazily to avoid a circular import with ``baselines``); tests inject fakes.
    """
    from scorer.baselines import _rank, b6_global_lgbm, b_llm_prior

    llm_fn = llm_fn or b_llm_prior
    b6_fn = b6_fn or b6_global_lgbm

    lam = select_lambda(_inner_folds(train_designs, llm_fn, b6_fn), grid)

    z_llm = _zscore(_arm_scores(llm_fn, train_labels, train_designs, test_designs))
    z_b6 = _zscore(_arm_scores(b6_fn, train_labels, train_designs, test_designs))
    blended = _blend(z_llm, z_b6, lam)
    return _rank([(d["design_id"], s) for d, s in zip(test_designs, blended)])
