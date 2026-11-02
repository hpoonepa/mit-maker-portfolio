from __future__ import annotations

from scorer.eval_types import (
    ENSEMBLE_INVERT_SUBSTRINGS,
    NUMERIC_METRIC_KEYS,
    is_real_binder,
    make_scored_design,
)


def test_make_scored_design_shape():
    sd = make_scored_design("d1", 0.91, 3)
    assert sd == {"design_id": "d1", "score": 0.91, "rank": 3}


def test_is_real_binder_requires_true_label():
    assert is_real_binder({"design_id": "d1", "binds": True}) is True
    assert is_real_binder({"design_id": "d2", "binds": False}) is False
    assert is_real_binder({"design_id": "d3", "binds": None}) is False


def test_numeric_metric_keys_use_computational_prefix():
    assert "computational__boltz2_min_ipsae" in NUMERIC_METRIC_KEYS
    assert "computational__boltz2_iptm" in NUMERIC_METRIC_KEYS
    assert "boltz2_min_ipsae" not in NUMERIC_METRIC_KEYS
    assert all(not k.startswith("experimental__") for k in NUMERIC_METRIC_KEYS)
    assert all(k.startswith("computational__") for k in NUMERIC_METRIC_KEYS)


def test_ensemble_invert_list_matches_notebook():
    assert ENSEMBLE_INVERT_SUBSTRINGS == ("pae", "rmsd", "clash", "energy", "ipae", "i_pae")
