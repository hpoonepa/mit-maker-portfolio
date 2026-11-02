from __future__ import annotations

import math

import pytest

from scorer.baselines import (
    BASELINE_BY_NAME,
    BASELINE_LADDER,
    b0_within_fold_min_ipsae,
    b1_within_fold_iptm,
    b3_overath_logistic,
    b4_null_random,
    b5_target_feature_conditioned_lgbm,
    b6_global_lgbm,
    b_llm_prior,
)
from scorer.data_loader import LGBM_FEATURE_KEYS
from scorer.llm_prior import Prior


def _design(did, target, binds, ipsae, sc=None, rmsd=None, extra=None):
    feats = {k: float("nan") for k in LGBM_FEATURE_KEYS}
    feats["best_ipsae"] = ipsae
    if sc is not None:
        feats["shape_complementarity"] = sc
    if rmsd is not None:
        feats["rmsd_binder"] = rmsd
    if extra:
        feats.update(extra)
    return {
        "design_id": did,
        "target": target,
        "binds": binds,
        "best_ipsae": ipsae,
        "features": feats,
    }


def _separable_fold(n=12):
    """Binders have high ipsae+sc+low rmsd, non-binders the opposite."""
    train, labels = [], []
    for i in range(n):
        train.append(_design(f"trP{i}", "X", True, 0.8 + 0.01 * i, sc=0.7, rmsd=1.0))
        labels.append(True)
        train.append(_design(f"trN{i}", "X", False, 0.2 + 0.01 * i, sc=0.3, rmsd=4.0))
        labels.append(False)
    test = [
        _design("teP1", "T", True, 0.85, sc=0.7, rmsd=1.1),
        _design("teP2", "T", True, 0.82, sc=0.68, rmsd=1.2),
        _design("teN1", "T", False, 0.25, sc=0.32, rmsd=3.8),
        _design("teN2", "T", False, 0.22, sc=0.30, rmsd=4.1),
    ]
    return labels, train, test


def _ranked_ids(scored):
    return [s["design_id"] for s in scored]


def test_b0_ranks_by_best_ipsae_descending():
    test = [
        _design("a", "T", False, 0.3),
        _design("b", "T", True, 0.9),
        _design("c", "T", False, float("nan")),  # missing -> last
        _design("d", "T", True, 0.6),
    ]
    out = b0_within_fold_min_ipsae([], [], test)
    assert _ranked_ids(out) == ["b", "d", "a", "c"]
    # ranks assigned 1..n
    assert [s["rank"] for s in out] == [1, 2, 3, 4]


def test_b0_needs_no_training():
    _, _, test = _separable_fold()
    out = b0_within_fold_min_ipsae(None, None, test)
    assert _ranked_ids(out)[0] in ("teP1", "teP2")


def test_b1_ranks_by_iptm_descending_and_missing_last():
    test = [
        _design("a", "T", False, 0.9, extra={"computational__boltz2_iptm": 0.3}),
        _design("b", "T", True, 0.2, extra={"computational__boltz2_iptm": 0.8}),
        _design("c", "T", False, 0.5),
    ]

    out = b1_within_fold_iptm([], [], test)

    assert _ranked_ids(out) == ["b", "a", "c"]


def test_b4_is_deterministic_and_permutes():
    test = [_design(f"d{i}", "T", i % 2 == 0, 0.5) for i in range(8)]
    a = _ranked_ids(b4_null_random([], [], test))
    b = _ranked_ids(b4_null_random([], [], test))
    assert a == b  # deterministic
    assert sorted(a) == sorted(d["design_id"] for d in test)


def test_b3_ranks_binders_above_nonbinders_on_clean_signal():
    labels, train, test = _separable_fold()
    out = _ranked_ids(b3_overath_logistic(labels, train, test))
    # both binders should outrank both non-binders
    assert set(out[:2]) == {"teP1", "teP2"}


def test_b6_lgbm_ranks_binders_above_nonbinders_on_clean_signal():
    labels, train, test = _separable_fold()
    out = _ranked_ids(b6_global_lgbm(labels, train, test))
    assert set(out[:2]) == {"teP1", "teP2"}


def test_b6_handles_nan_features_without_imputation():
    labels, train, test = _separable_fold()
    # blank out a feature entirely on some rows -> LGBM must still run
    for d in train[::3]:
        d["features"]["computational__boltz2_iptm"] = float("nan")
    out = b6_global_lgbm(labels, train, test)
    assert len(out) == len(test)


def _target_signal_fold(n=12):
    """A fold where binding depends ONLY on the TARGET, not design features.

    Two real targets present in target_features.csv with distinct feature
    vectors: every PDL1 design binds, every PD1 design does not. ALL designs
    share identical design-level numeric features (same ipsae/sc/rmsd), so a
    model WITHOUT target features (B6) sees pure noise and cannot separate the
    two test designs; a model WITH target features (B5) can split on the target
    feature columns. Hence B5 != B6 on this fold.
    """
    train, labels = [], []
    for i in range(n):
        train.append(_design(f"pdl1_{i}", "PDL1", True, 0.5, sc=0.5, rmsd=2.0))
        labels.append(True)
        train.append(_design(f"pd1_{i}", "PD1", False, 0.5, sc=0.5, rmsd=2.0))
        labels.append(False)
    test = [
        _design("te_pdl1", "PDL1", True, 0.5, sc=0.5, rmsd=2.0),
        _design("te_pd1", "PD1", False, 0.5, sc=0.5, rmsd=2.0),
    ]
    return labels, train, test


def test_b5_augments_target_features_and_differs_from_b6():
    """B5 conditions on target features; B6 does not. On a fold where the only
    signal is the target identity, B5 must rank the binder's target first while
    B6 (target-blind, identical design features) cannot reproduce that order."""
    labels, train, test = _target_signal_fold()
    out5 = _ranked_ids(b5_target_feature_conditioned_lgbm(labels, train, test))
    out6 = _ranked_ids(b6_global_lgbm(labels, train, test))
    # B5 learns target signal -> the PDL1 (binder) design ranks first.
    assert out5[0] == "te_pdl1"
    # B6 is target-blind on identical design features -> cannot match B5's order.
    assert out5 != out6


def test_ladder_contains_expected_baselines():
    names = [name for name, _ in BASELINE_LADDER]
    assert names == ["B0", "B_IPTM", "B3", "B4", "B5", "B6", "B_LLM", "B_STACK"]
    for _, fn in BASELINE_LADDER:
        assert callable(fn)


# ---------------------------------------------------------------------------
# B_LLM — LLM-per-target signed prior scorer
# ---------------------------------------------------------------------------
def _llm_train(n=10):
    """Train designs with varied best_ipsae/sc/rmsd so per-metric std > 0."""
    train, labels = [], []
    for i in range(n):
        train.append(
            _design(f"tr{i}", "T", i % 2 == 0, 0.3 + 0.05 * i,
                    sc=0.2 + 0.05 * i, rmsd=1.0 + 0.2 * i)
        )
        labels.append(i % 2 == 0)
    return labels, train


def test_b_llm_ranks_binder_above_nonbinder():
    prior = Prior(weights={"computational__boltz2_min_ipsae": 1.0})
    labels, train = _llm_train()
    test = [
        _design("binder", "T", True, 0.9),
        _design("nonbinder", "T", False, 0.2),
    ]
    out = _ranked_ids(b_llm_prior(labels, train, test, priors={"T": prior}, target="T"))
    assert out.index("binder") < out.index("nonbinder")


def test_b_llm_alias_matches_b0():
    """A prior weighting ONLY boltz2_min_ipsae ranks identically to B0 (which
    ranks by best_ipsae) — proves the alias maps it to best_ipsae, not skipped."""
    prior = Prior(weights={"computational__boltz2_min_ipsae": 1.0})
    labels, train = _llm_train()
    test = [
        _design("a", "T", False, 0.3),
        _design("b", "T", True, 0.9),
        _design("d", "T", True, 0.6),
    ]
    out = _ranked_ids(b_llm_prior(labels, train, test, priors={"T": prior}, target="T"))
    b0 = _ranked_ids(b0_within_fold_min_ipsae(labels, train, test))
    assert out == b0


def test_b_llm_differs_from_b0_when_upweighting_non_ipsae():
    prior = Prior(weights={"shape_complementarity": 1.0})
    train = [
        _design("tr0", "T", True, 0.5, sc=0.2),
        _design("tr1", "T", False, 0.5, sc=0.8),
    ]
    labels = [True, False]
    test = [
        _design("hi_sc", "T", True, 0.2, sc=0.9),
        _design("lo_sc", "T", False, 0.9, sc=0.1),
    ]
    out = _ranked_ids(b_llm_prior(labels, train, test, priors={"T": prior}, target="T"))
    b0 = _ranked_ids(b0_within_fold_min_ipsae(labels, train, test))
    assert out[0] == "hi_sc"   # ranked by shape_complementarity
    assert out != b0           # B0 ranks by ipsae -> lo_sc first


def test_b_llm_negative_weight_respects_sign_no_double_flip():
    """Negative weight on rmsd_binder ranks LOW-rmsd ABOVE high-rmsd."""
    prior = Prior(weights={"rmsd_binder": -1.0})
    train = [
        _design("tr0", "T", True, 0.5, rmsd=1.0),
        _design("tr1", "T", False, 0.5, rmsd=5.0),
    ]
    labels = [True, False]
    test = [
        _design("low_rmsd", "T", True, 0.5, rmsd=1.0),
        _design("high_rmsd", "T", False, 0.5, rmsd=5.0),
    ]
    out = _ranked_ids(b_llm_prior(labels, train, test, priors={"T": prior}, target="T"))
    assert out[0] == "low_rmsd"


def test_b_llm_leakage_safe_uses_train_mean():
    """Normalization uses TRAIN-only stats: a test value == train mean scores 0."""
    prior = Prior(weights={"shape_complementarity": 1.0})
    train = [
        _design("tr0", "T", True, 0.5, sc=0.4),
        _design("tr1", "T", False, 0.5, sc=0.6),  # train mean sc = 0.5
    ]
    labels = [True, False]
    test = [
        _design("at_mean", "T", True, 0.5, sc=0.5),   # z = 0 -> score 0
        _design("above", "T", True, 0.5, sc=0.9),
    ]
    out = b_llm_prior(labels, train, test, priors={"T": prior}, target="T")
    by_id = {s["design_id"]: s for s in out}
    assert by_id["at_mean"]["score"] == pytest.approx(0.0, abs=1e-9)
    assert by_id["above"]["score"] > 0
    assert out[0]["design_id"] == "above"


def test_b_llm_falls_back_when_no_prior_for_target():
    prior = Prior(weights={"shape_complementarity": 1.0})
    labels, train = _llm_train()
    test = [
        _design("a", "T", False, 0.3),
        _design("b", "T", True, 0.9),
    ]
    out = _ranked_ids(
        b_llm_prior(labels, train, test, priors={"OTHER": prior}, target="NIPAH")
    )
    b0 = _ranked_ids(b0_within_fold_min_ipsae(labels, train, test))
    assert out == b0


def test_b_llm_failure_penalty_demotes_over_threshold():
    prior = Prior(
        weights={"computational__boltz2_min_ipsae": 1.0},
        failure_penalties={"cysteine_fraction": {"gt": 0.08, "penalty": 1.0}},
    )
    train = [
        _design("tr0", "T", True, 0.4),
        _design("tr1", "T", False, 0.8),
    ]
    labels = [True, False]
    # Same ipsae -> same weighted score. "aaa_bad" sorts first by tie-break,
    # so only the penalty can push it below "zzz_good".
    test = [
        _design("aaa_bad", "T", True, 0.6, extra={"cysteine_fraction": 0.2}),
        _design("zzz_good", "T", True, 0.6, extra={"cysteine_fraction": 0.0}),
    ]
    out = _ranked_ids(b_llm_prior(labels, train, test, priors={"T": prior}, target="T"))
    assert out[0] == "zzz_good"
    assert out[1] == "aaa_bad"


def test_b_llm_registered_and_auto_resolves_from_default_priors():
    """3-arg form (priors/target None) resolves the cached default priors file
    by the test designs' target without crashing."""
    assert "B_LLM" in BASELINE_BY_NAME
    labels, train = _llm_train()
    # Use a real target present in data/processed/llm_priors.json.
    for d in train:
        d["target"] = "PDL1"
    test = [
        _design("p_hi", "PDL1", True, 0.9),
        _design("p_lo", "PDL1", False, 0.2),
    ]
    out = BASELINE_BY_NAME["B_LLM"](labels, train, test)
    assert sorted(s["design_id"] for s in out) == ["p_hi", "p_lo"]
    assert [s["rank"] for s in out] == [1, 2]


def test_all_baselines_return_full_ranked_set():
    labels, train, test = _separable_fold()
    for _, fn in BASELINE_LADDER:
        out = fn(labels, train, test)
        assert len(out) == len(test)
        assert sorted(s["design_id"] for s in out) == sorted(d["design_id"] for d in test)
        assert [s["rank"] for s in out] == list(range(1, len(test) + 1))
