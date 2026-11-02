"""Tests for scorer.metric_power — within-target discriminative power.

Synthetic-only (no network); one light smoke check against real data.
"""

from __future__ import annotations

import math
import os

import pytest

from scorer.metric_power import (
    METRIC_KEYS,
    _auc,
    discriminative_power,
    format_power_table,
    within_target_auc,
)


def _design(target: str, binds: bool, **features) -> dict:
    """Build a design dict; ipSAE goes to best_ipsae, rest to features."""
    best = features.pop("best_ipsae", float("nan"))
    return {
        "design_id": f"{target}:{len(features)}:{binds}:{hash(tuple(sorted(features.items())))}",
        "target": target,
        "sequence": "X",
        "binds": binds,
        "best_ipsae": best,
        "features": features,
    }


# ---------------------------------------------------------------- METRIC_KEYS


def test_metric_keys_has_25_unique():
    assert len(METRIC_KEYS) == 25
    assert len(set(METRIC_KEYS)) == 25


def test_metric_keys_contains_expected_groups():
    assert "computational__boltz2_min_ipsae" in METRIC_KEYS
    assert "shape_complementarity" in METRIC_KEYS
    assert "net_charge_ph7" in METRIC_KEYS
    assert "bio__immunogenicity_proxy" in METRIC_KEYS
    # molecular_weight is intentionally excluded (6 sequence metrics, not 7).
    assert "molecular_weight" not in METRIC_KEYS


# ---------------------------------------------------------------- _auc


def test_auc_perfect_separation():
    pairs = [(3.0, True), (4.0, True), (1.0, False), (2.0, False)]
    assert _auc(pairs) == 1.0


def test_auc_reversed_separation():
    pairs = [(1.0, True), (2.0, True), (3.0, False), (4.0, False)]
    assert _auc(pairs) == 0.0


def test_auc_interleaved_near_half():
    # pos={2,3} straddle neg={1,4}: 2 wins / 4 comparisons = 0.5.
    pairs = [(2.0, True), (3.0, True), (1.0, False), (4.0, False)]
    assert _auc(pairs) == 0.5


def test_auc_all_ties_is_half():
    pairs = [(1.0, True), (1.0, True), (1.0, False), (1.0, False)]
    assert _auc(pairs) == 0.5


def test_auc_empty_class_returns_none():
    assert _auc([(1.0, True), (2.0, True)]) is None
    assert _auc([(1.0, False), (2.0, False)]) is None


# ---------------------------------------------------------------- within_target_auc


_M = "shape_complementarity"  # a real metric key; higher=better
_R = "bio__disorder_fraction"  # used as a "random" metric
_L = "rmsd_binder"  # a real lower-is-better metric key


def test_within_target_perfect_separation_mean_one():
    designs = []
    # T1: separates (binders high), with an offset distinct from T2.
    designs += [_design("T1", True, **{_M: 10.0}), _design("T1", True, **{_M: 11.0})]
    designs += [_design("T1", False, **{_M: 1.0}), _design("T1", False, **{_M: 2.0})]
    # T2: also separates but on a totally different scale — within-target only.
    designs += [_design("T2", True, **{_M: 110.0}), _design("T2", True, **{_M: 111.0})]
    designs += [_design("T2", False, **{_M: 101.0}), _design("T2", False, **{_M: 102.0})]
    out = within_target_auc(designs)
    assert out[_M] == pytest.approx(1.0)


def test_within_target_random_metric_near_half():
    designs = []
    designs += [_design("T1", True, **{_R: 1.0}), _design("T1", True, **{_R: 4.0})]
    designs += [_design("T1", False, **{_R: 2.0}), _design("T1", False, **{_R: 3.0})]
    designs += [_design("T2", True, **{_R: 2.0}), _design("T2", True, **{_R: 3.0})]
    designs += [_design("T2", False, **{_R: 1.0}), _design("T2", False, **{_R: 4.0})]
    out = within_target_auc(designs)
    assert out[_R] == pytest.approx(0.5)


def test_within_target_skips_nan_target_scores_other():
    designs = []
    # T1: metric is all-NaN -> unscoreable, must be skipped.
    designs += [_design("T1", True, **{_M: float("nan")}), _design("T1", False, **{_M: float("nan")})]
    # T2: metric perfectly separates.
    designs += [_design("T2", True, **{_M: 10.0}), _design("T2", False, **{_M: 1.0})]
    out = within_target_auc(designs)
    assert out[_M] == pytest.approx(1.0)  # mean over scoreable targets only (just T2)


def test_within_target_skips_single_class_target():
    designs = [
        _design("T1", True, **{_M: 10.0}),
        _design("T1", True, **{_M: 11.0}),  # no negatives -> skipped
        _design("T2", True, **{_M: 9.0}),
        _design("T2", False, **{_M: 1.0}),  # scoreable
    ]
    out = within_target_auc(designs)
    assert out[_M] == pytest.approx(1.0)


def test_within_target_lower_is_better_below_half():
    designs = []
    # binders have LOWER values -> directional AUC < 0.5 (not abs'd).
    designs += [_design("T1", True, **{_L: 1.0}), _design("T1", True, **{_L: 2.0})]
    designs += [_design("T1", False, **{_L: 10.0}), _design("T1", False, **{_L: 11.0})]
    out = within_target_auc(designs)
    assert out[_L] == pytest.approx(0.0)
    assert out[_L] < 0.5


# ---------------------------------------------------------------- discriminative_power


def test_discriminative_power_formula():
    designs = [_design("T1", True, **{_M: 10.0}), _design("T1", False, **{_M: 1.0})]
    auc = within_target_auc(designs)
    pwr = discriminative_power(designs)
    assert pwr[_M] == pytest.approx(abs(auc[_M] - 0.5) * 2)
    assert pwr[_M] == pytest.approx(1.0)


def test_discriminative_power_high_for_lower_is_better():
    designs = [_design("T1", True, **{_L: 1.0}), _design("T1", False, **{_L: 10.0})]
    pwr = discriminative_power(designs)
    # AUC < 0.5 but power should be HIGH (direction-agnostic strength).
    assert pwr[_L] == pytest.approx(1.0)


# ---------------------------------------------------------------- leakage safety


def test_leakage_only_uses_passed_designs():
    # T1 perfectly separates (AUC 1.0); T2 perfectly reverses (AUC 0.0).
    t1 = [_design("T1", True, **{_M: 10.0}), _design("T1", False, **{_M: 1.0})]
    t2 = [_design("T2", True, **{_M: 1.0}), _design("T2", False, **{_M: 10.0})]
    both = within_target_auc(t1 + t2)
    only_t1 = within_target_auc(t1)
    assert only_t1[_M] == pytest.approx(1.0)
    assert both[_M] == pytest.approx(0.5)  # mean of 1.0 and 0.0
    assert both[_M] != only_t1[_M]  # excluding a target changes the result


# ---------------------------------------------------------------- format_power_table


def test_format_power_table_sorted_and_labeled():
    within = {"hi": 0.9, "lo": 0.1, "weak": 0.55}
    discrim = {"hi": 0.8, "lo": 0.8, "weak": 0.1}
    table = format_power_table(within, discrim)
    lines = [ln for ln in table.splitlines() if ln.strip()]
    # 'weak' (power 0.1) must come last; hi/lo (power 0.8) before it.
    assert lines[-1].split()[0] == "weak"
    # direction labels
    hi_line = next(ln for ln in lines if ln.startswith("hi"))
    lo_line = next(ln for ln in lines if ln.startswith("lo"))
    assert "higher=better" in hi_line
    assert "lower=better" in lo_line
    assert "AUC=0.900" in hi_line
    assert "power=0.80" in hi_line


# ---------------------------------------------------------------- real-data smoke


def test_real_data_smoke_actifptm_and_interface_in_top3():
    from scorer.data_loader import load_designs

    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "processed", "labeled_features_bio.csv"
    )
    if not os.path.exists(path):
        pytest.skip("real data not present")
    pwr = discriminative_power(load_designs(path))
    top3 = [k for k, _ in sorted(pwr.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    assert "computational__actifptm" in top3
    assert "computational__interface_residues" in top3
