from __future__ import annotations

import math

import pytest

from scorer.eval_metrics import precision_at_k, recall_at_budget, fold_adaptive_k


def test_precision_at_k_basic():
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a", "c"}, k=2) == 0.5


def test_precision_at_k_target_smaller_than_k_uses_effective_k():
    assert precision_at_k(["a", "b", "c"], {"a", "b"}, k=20) == pytest.approx(2 / 3)


def test_precision_at_k_empty_ranking_is_zero():
    assert precision_at_k([], {"a"}, k=5) == 0.0


def test_precision_at_k_rejects_nonpositive_k():
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, k=0)


def test_recall_at_budget_basic():
    assert recall_at_budget(["a", "b", "c", "d"], {"a", "d"}, budget=2) == 0.5


def test_recall_at_budget_no_positives_is_nan():
    assert math.isnan(recall_at_budget(["a", "b"], set(), budget=2))


def test_recall_at_budget_budget_exceeds_n():
    assert recall_at_budget(["a", "b"], {"a", "b"}, budget=50) == 1.0


def test_fold_adaptive_k_caps_at_n_pos():
    k = fold_adaptive_k(n_pos=3, default_k=20)
    assert k == 3


def test_fold_adaptive_k_uses_default_when_n_pos_large():
    k = fold_adaptive_k(n_pos=50, default_k=20)
    assert k == 20
