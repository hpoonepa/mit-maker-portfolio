from __future__ import annotations

import math

import pytest

from scorer.diagnostics import ipw_delta


def test_uniform_propensity_equals_plain_mean():
    deltas = [0.1, 0.2, 0.3, 0.0]
    p = [0.5, 0.5, 0.5, 0.5]
    assert ipw_delta(deltas, p) == pytest.approx(sum(deltas) / len(deltas))


def test_low_propensity_designs_upweighted():
    # design with p=0.1 (rare to be tested) gets ~9x the weight of p=0.9
    deltas = [1.0, 0.0]
    p = [0.1, 0.9]
    out = ipw_delta(deltas, p)
    # weights 1/0.1=10, 1/0.9~1.111 -> normalized ~0.9 vs 0.1
    assert out == pytest.approx(10 / (10 + 1 / 0.9), rel=1e-6)
    assert out > 0.5  # rare-tested positive dominates


def test_propensity_clipped_to_avoid_div_by_zero():
    deltas = [1.0, 1.0]
    p = [0.0, 1.0]  # clipped to 0.01 and 0.99
    out = ipw_delta(deltas, p)
    assert math.isfinite(out)
    assert out == pytest.approx(1.0)


def test_empty_returns_nan():
    assert math.isnan(ipw_delta([], []))


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        ipw_delta([0.1, 0.2], [0.5])
