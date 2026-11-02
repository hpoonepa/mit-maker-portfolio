from __future__ import annotations

import math

from scorer.bootstrap_ci import paired_bca_ci


def test_all_positive_deltas_ci_lower_bound_above_zero():
    deltas = [0.10, 0.12, 0.08, 0.15, 0.09, 0.11, 0.13, 0.07, 0.14, 0.10, 0.12]
    r = paired_bca_ci(deltas, n_boot=2000, seed=0)
    assert r["point"] > 0
    assert r["lo"] > 0
    assert r["n"] == 11
    assert r["n_positive_deltas"] == 11
    # all positive -> sign test highly significant
    assert r["sign_test_p"] < 0.01


def test_symmetric_around_zero_ci_straddles_zero():
    deltas = [-0.10, 0.10, -0.08, 0.08, -0.12, 0.12, -0.05, 0.05, -0.09, 0.09, 0.0]
    r = paired_bca_ci(deltas, n_boot=2000, seed=0)
    assert r["lo"] < 0 < r["hi"]
    # sign test should not be significant
    assert r["sign_test_p"] > 0.1


def test_deterministic_given_seed():
    deltas = [0.05, -0.02, 0.1, 0.03, -0.01, 0.08, 0.02, 0.06, -0.03, 0.04, 0.07]
    a = paired_bca_ci(deltas, n_boot=1000, seed=42)
    b = paired_bca_ci(deltas, n_boot=1000, seed=42)
    assert a["lo"] == b["lo"] and a["hi"] == b["hi"]


def test_wilcoxon_computed_when_n_ge_10_else_nan():
    big = [0.05, -0.02, 0.1, 0.03, -0.01, 0.08, 0.02, 0.06, -0.03, 0.04]
    r = paired_bca_ci(big, n_boot=500, seed=0)
    assert not math.isnan(r["wilcoxon_p"])
    small = [0.05, 0.1, 0.03]
    rs = paired_bca_ci(small, n_boot=500, seed=0)
    assert math.isnan(rs["wilcoxon_p"])


def test_n_positive_deltas_counts_strictly_positive():
    deltas = [0.1, 0.0, -0.1, 0.2, 0.0]
    r = paired_bca_ci(deltas, n_boot=200, seed=0)
    assert r["n_positive_deltas"] == 2
