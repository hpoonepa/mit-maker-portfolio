"""Tests for B_STACK — convex blend of B_LLM + B6 with nested-LOTO lambda.

The blend/selection logic is tested in isolation with INJECTED fake arm scorers
(no LightGBM, no live priors) so the tests are fast and deterministic. The two
integration tests prove the end-to-end wiring: when one arm perfectly separates
binders, nested selection drives lambda to that arm and the stack matches it.
"""

from __future__ import annotations

import math

from scorer.baselines import BASELINE_BY_NAME
from scorer.eval_metrics import fold_adaptive_k, precision_at_k
from scorer.eval_types import is_real_binder, make_scored_design
from scorer.stack import (
    DEFAULT_LAMBDA,
    _blend,
    _zscore,
    b_stack,
    select_lambda,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _d(did: str, target: str, binds: bool) -> dict:
    return {"design_id": did, "target": target, "binds": binds, "features": {}}


def _pool(spec: dict[str, tuple[int, int]]) -> list[dict]:
    """spec = {target: (n_pos, n_neg)} -> flat design list."""
    out: list[dict] = []
    for t, (npos, nneg) in spec.items():
        out += [_d(f"{t}_p{i}", t, True) for i in range(npos)]
        out += [_d(f"{t}_n{i}", t, False) for i in range(nneg)]
    return out


def _rank_pairs(pairs):
    ordered = sorted(pairs, key=lambda p: (-p[1], p[0]))
    return [make_scored_design(did, sc, i + 1) for i, (did, sc) in enumerate(ordered)]


def fake_perfect(train_labels, train, test):
    """A stand-in scorer that perfectly separates binders (ranks them first)."""
    return _rank_pairs([(d["design_id"], 1.0 if d["binds"] else 0.0) for d in test])


def fake_useless(train_labels, train, test):
    """A stand-in scorer with no signal (constant score)."""
    return _rank_pairs([(d["design_id"], 0.0) for d in test])


# --------------------------------------------------------------------------- #
# _zscore
# --------------------------------------------------------------------------- #
def test_zscore_centers_and_orders():
    z = _zscore([1.0, 2.0, 3.0])
    assert abs(sum(z)) < 1e-9      # centered
    assert z[0] < z[1] < z[2]      # order preserved


def test_zscore_all_equal_returns_zeros():
    assert _zscore([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]


def test_zscore_nan_contributes_zero():
    z = _zscore([1.0, float("nan"), 3.0])
    assert z[1] == 0.0             # missing -> neutral, not NaN
    assert not any(math.isnan(v) for v in z)


# --------------------------------------------------------------------------- #
# _blend
# --------------------------------------------------------------------------- #
def test_blend_is_convex_midpoint():
    assert _blend([1.0, 0.0], [0.0, 1.0], 0.5) == [0.5, 0.5]


def test_blend_endpoints_select_single_arm():
    a, b = [1.0, 2.0], [3.0, 4.0]
    assert _blend(a, b, 1.0) == a   # lambda=1 -> LLM arm
    assert _blend(a, b, 0.0) == b   # lambda=0 -> data arm


# --------------------------------------------------------------------------- #
# select_lambda (pure, on precomputed inner folds)
# --------------------------------------------------------------------------- #
def _inner(z_llm, z_b6, ids, pos_ids, k):
    return {"z_llm": z_llm, "z_b6": z_b6, "ids": ids, "pos_ids": pos_ids, "k": k}


def test_select_lambda_prefers_llm_when_only_llm_separates():
    # LLM ranks p first; the data arm strongly ranks the non-binder up, so ONLY
    # lambda=1 puts p on top (already at 0.75 the data arm overtakes) -> unique max.
    fold = _inner([1.0, 0.0], [0.0, 10.0], ["p", "n"], {"p"}, 1)
    assert select_lambda([fold], (0.0, 0.25, 0.5, 0.75, 1.0)) == 1.0


def test_select_lambda_prefers_data_when_only_data_separates():
    # Symmetric: only lambda=0 (pure data arm) puts p on top.
    fold = _inner([0.0, 10.0], [1.0, 0.0], ["p", "n"], {"p"}, 1)
    assert select_lambda([fold], (0.0, 0.25, 0.5, 0.75, 1.0)) == 0.0


def test_select_lambda_tiebreak_prefers_balanced():
    # both arms perfectly rank -> every lambda ties -> prefer 0.5 (balanced)
    fold = _inner([1.0, -1.0], [1.0, -1.0], ["p", "n"], {"p"}, 1)
    assert select_lambda([fold], (0.0, 0.25, 0.5, 0.75, 1.0)) == 0.5


# --------------------------------------------------------------------------- #
# b_stack — registration + end-to-end wiring
# --------------------------------------------------------------------------- #
def test_b_stack_registered():
    assert "B_STACK" in BASELINE_BY_NAME


def _stack_precision(train, test, llm_fn, b6_fn):
    labels = [is_real_binder(d) for d in train]
    ranked = [s["design_id"] for s in
              b_stack(labels, train, test, llm_fn=llm_fn, b6_fn=b6_fn)]
    pos = {d["design_id"] for d in test if d["binds"]}
    return precision_at_k(ranked, pos, fold_adaptive_k(len(pos)))


def test_b_stack_matches_llm_arm_when_llm_perfect():
    train = _pool({"A": (10, 10), "B": (10, 10), "C": (10, 10)})
    test = _pool({"T": (10, 10)})
    # nested selection sees LLM perfect on A/B/C -> lambda->1 -> perfect on T
    assert _stack_precision(train, test, fake_perfect, fake_useless) == 1.0


def test_b_stack_matches_data_arm_when_data_perfect():
    train = _pool({"A": (10, 10), "B": (10, 10), "C": (10, 10)})
    test = _pool({"T": (10, 10)})
    assert _stack_precision(train, test, fake_useless, fake_perfect) == 1.0


def test_b_stack_no_inner_targets_uses_default_lambda():
    # train has no well-powered target (all <10 pos) -> fall back to DEFAULT_LAMBDA,
    # still returns a full ranking of the test fold without error.
    train = _pool({"A": (3, 3), "B": (2, 4)})
    test = _pool({"T": (10, 10)})
    labels = [is_real_binder(d) for d in train]
    ranked = b_stack(labels, train, test, llm_fn=fake_perfect, b6_fn=fake_useless)
    assert len(ranked) == len(test)
    assert 0.0 <= DEFAULT_LAMBDA <= 1.0
