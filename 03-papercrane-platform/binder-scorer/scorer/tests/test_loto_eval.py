"""Tests for loto_eval.py (Task A8) — run_loto_eval + three-zone verdict."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from scorer.loto_eval import (
    THREE_ZONE_POLICY,
    _three_zone_verdict,
    run_loto_eval,
)

# ---------------------------------------------------------------------------
# _three_zone_verdict — pure logic
# ---------------------------------------------------------------------------


def test_verdict_real_product_when_ci_lo_positive():
    ci = {"lo": 0.02, "hi": 0.10}
    assert _three_zone_verdict(ci, n_pos_deltas=6, n_targets=11) == "real_product"


def test_verdict_real_product_when_nearly_all_wins():
    # wins >= n_targets - 1 → real_product even if CI straddles
    ci = {"lo": -0.01, "hi": 0.20}
    assert _three_zone_verdict(ci, n_pos_deltas=10, n_targets=11) == "real_product"


def test_verdict_fall_back_when_ci_hi_negative():
    ci = {"lo": -0.20, "hi": -0.02}
    assert _three_zone_verdict(ci, n_pos_deltas=2, n_targets=11) == "fall_back_to_global"


def test_verdict_fall_back_when_few_wins():
    # wins <= n_targets//2 - 1 → fall back. n=11 → threshold = 4
    ci = {"lo": -0.10, "hi": 0.10}
    assert _three_zone_verdict(ci, n_pos_deltas=4, n_targets=11) == "fall_back_to_global"


def test_verdict_inconclusive_middle():
    ci = {"lo": -0.05, "hi": 0.08}
    assert _three_zone_verdict(ci, n_pos_deltas=6, n_targets=11) == "inconclusive"


def test_verdict_subnormal_lo_does_not_flip_to_real_product():
    # Knife-edge bug (the real B3 Nipah-OUT case): BCa lo = 5.55e-18 (FP dust)
    # with only 3/10 wins falsely read "real_product" pre-fix. It must NOT.
    # With wins=3 (<= 10//2-1=4) the correct verdict is fall_back_to_global.
    ci = {"lo": 5.55e-18, "hi": 0.198}
    assert _three_zone_verdict(ci, n_pos_deltas=3, n_targets=10) != "real_product"
    assert _three_zone_verdict(ci, n_pos_deltas=3, n_targets=10) == "fall_back_to_global"


def test_verdict_subnormal_lo_with_mid_wins_is_inconclusive_not_real():
    # Same FP-dust lo, but enough wins to escape the fall_back floor (6/10):
    # must land inconclusive, never real_product on subnormal noise alone.
    ci = {"lo": 5.55e-18, "hi": 0.198}
    assert _three_zone_verdict(ci, n_pos_deltas=6, n_targets=10) == "inconclusive"


def test_three_zone_policy_is_documented_string():
    assert isinstance(THREE_ZONE_POLICY, str)
    assert "B5" in THREE_ZONE_POLICY
    assert len(THREE_ZONE_POLICY) > 50


# ---------------------------------------------------------------------------
# run_loto_eval — integration on the real CSV
# ---------------------------------------------------------------------------

CSV = Path(__file__).resolve().parents[2] / "data" / "processed" / "labeled_features.csv"


@pytest.fixture(scope="module")
def real_result():
    return run_loto_eval(CSV, candidate="B6", baseline="B0")


def test_run_returns_eleven_folds(real_result):
    assert len(real_result["per_target"]) == 11


def test_run_verdict_in_allowed_set(real_result):
    assert real_result["verdict"] in {
        "real_product",
        "fall_back_to_global",
        "inconclusive",
    }


def test_run_point_delta_is_finite(real_result):
    point = real_result["aggregate"]["precision"]["point"]
    assert math.isfinite(point)


def test_run_each_target_row_has_required_keys(real_result):
    for row in real_result["per_target"]:
        for key in (
            "target",
            "k",
            "n_pos",
            "candidate_precision_at_k",
            "baseline_precision_at_k",
            "delta_precision",
            "candidate_recall_at_budget",
            "baseline_recall_at_budget",
            "delta_recall",
        ):
            assert key in row, f"missing {key}"


def test_run_reports_nipah_in_and_out(real_result):
    assert "nipah_in" in real_result
    assert "nipah_out" in real_result


def test_run_includes_power_statement(real_result):
    assert isinstance(real_result["power_statement"], str)
    assert "MDE" in real_result["power_statement"]


def test_run_aggregate_has_ci_and_sign_test(real_result):
    agg = real_result["aggregate"]["precision"]
    for key in ("point", "lo", "hi", "sign_test_p", "n_positive_deltas"):
        assert key in agg
