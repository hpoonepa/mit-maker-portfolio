"""test_llm_prior.py — TDD for the LLM-per-target signed importance prior.

All tests use the fake ``RecordedClient`` — NO network is ever touched.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from scorer.llm_prior import (
    MENU_FEATURE_KEYS,
    Prior,
    RecordedClient,
    _validate_and_normalize,
    build_prior_prompt,
    generate_prior,
    load_priors,
)


# --- Prior dataclass --------------------------------------------------------


def test_prior_is_frozen():
    p = Prior(
        weights={"best_ipsae": 1.0},
        failure_penalties={},
        epitope_residues=[1, 2],
        liabilities=[],
        proposed_features=[],
        rationale="",
        citations=[],
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.rationale = "mutated"  # type: ignore[misc]


# --- _validate_and_normalize ------------------------------------------------


def test_normalize_l1_on_abs_preserves_sign():
    out = _validate_and_normalize({"best_ipsae": 3.0, "cysteine_fraction": -1.0})
    assert math.isclose(sum(abs(w) for w in out.values()), 1.0)
    assert out["best_ipsae"] > 0
    assert out["cysteine_fraction"] < 0
    assert math.isclose(out["best_ipsae"], 0.75)
    assert math.isclose(out["cysteine_fraction"], -0.25)


def test_normalize_negative_weight_survives():
    out = _validate_and_normalize({"bio__aggregation_propensity": -2.0,
                                   "best_ipsae": 2.0})
    assert out["bio__aggregation_propensity"] < 0
    assert math.isclose(out["bio__aggregation_propensity"], -0.5)


def test_normalize_single_negative_keeps_sign():
    out = _validate_and_normalize({"computational__boltz2_min_ipsae": -3.0})
    assert out == {"computational__boltz2_min_ipsae": -1.0}


# --- menu pinning -----------------------------------------------------------


def test_menu_is_exactly_26_unique_keys():
    assert len(MENU_FEATURE_KEYS) == 26
    assert len(set(MENU_FEATURE_KEYS)) == 26
    for key in ("bio__aggregation_propensity",
                "computational__boltz2_min_ipsae",
                "net_charge_ph7"):
        assert key in MENU_FEATURE_KEYS


def test_normalize_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown metric key"):
        _validate_and_normalize({"not_a_real_metric": 1.0})


def test_normalize_non_finite_raises():
    with pytest.raises(ValueError):
        _validate_and_normalize({"best_ipsae": float("inf")})
    with pytest.raises(ValueError):
        _validate_and_normalize({"best_ipsae": float("nan")})


def test_normalize_all_zero_raises():
    with pytest.raises(ValueError, match="empty or all-zero"):
        _validate_and_normalize({"best_ipsae": 0.0})
    with pytest.raises(ValueError, match="empty or all-zero"):
        _validate_and_normalize({})


def test_normalize_drops_zeros():
    out = _validate_and_normalize({"best_ipsae": 1.0, "seq_length": 0.0})
    assert "seq_length" not in out
    assert math.isclose(out["best_ipsae"], 1.0)


# --- load_priors ------------------------------------------------------------


def _write_json(tmp_path, obj):
    p = tmp_path / "priors.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_load_priors_round_trips_two_targets_with_negative(tmp_path):
    obj = {
        "EGFR": {
            "weights": {"best_ipsae": 3.0, "bio__aggregation_propensity": -1.0},
            "epitope_residues": [355, 356],
            "liabilities": ["aggregation"],
            "rationale": "domain III epitope",
            "citations": ["12345678"],
        },
        "PD1": {
            "weights": {"computational__boltz2_min_ipsae": 1.0},
        },
    }
    priors = load_priors(_write_json(tmp_path, obj))
    assert set(priors) == {"EGFR", "PD1"}
    egfr = priors["EGFR"]
    assert isinstance(egfr, Prior)
    assert egfr.weights["bio__aggregation_propensity"] < 0
    assert math.isclose(sum(abs(w) for w in egfr.weights.values()), 1.0)
    assert egfr.epitope_residues == [355, 356]
    # defaults for missing optional fields
    pd1 = priors["PD1"]
    assert pd1.epitope_residues == []
    assert pd1.liabilities == []
    assert pd1.failure_penalties == {}
    assert pd1.proposed_features == []
    assert pd1.rationale == ""
    assert pd1.citations == []


def test_load_priors_unknown_key_raises(tmp_path):
    obj = {"EGFR": {"weights": {"bogus_metric": 1.0}}}
    with pytest.raises(ValueError, match="unknown metric key"):
        load_priors(_write_json(tmp_path, obj))


# --- build_prior_prompt -----------------------------------------------------


def _features_row():
    return {
        "log_length": 5.3,
        "disorder_fraction": 0.57,
        "frac_helix": 0.28,
        "frac_strand": 0.39,
        "frac_loop": 0.33,
        "pocket_volume": "",
        "druggability": "",
        "epitope_hydrophobicity": -0.28,
        "epitope_net_charge": 0.01,
        "frac_polar": 0.56,
        "interface_class": "sheet_flat",
    }


def _literature():
    return {
        "abstracts": [
            {"pmid": "111", "title": "EGFR domain III binder",
             "abstract": "A cetuximab-competitive epitope on domain III."},
        ],
        "open_targets": {"approvedSymbol": "EGFR",
                         "safetyLiabilities": [{"event": "rash"}]},
    }


_POWER_TABLE = (
    "computational__actifptm  AUC=0.735  power=0.47  (higher=better)\n"
    "computational__interface_residues  AUC=0.730  power=0.46  (higher=better)\n"
    "computational__boltz2_min_ipsae  AUC=0.720  power=0.44  (higher=better)\n"
    "bio__aggregation_propensity  AUC=0.520  power=0.04  (higher=better)"
)


def test_build_prompt_includes_required_pieces():
    prompt = build_prior_prompt(
        "EGFR", _features_row(), _literature(), MENU_FEATURE_KEYS,
        metric_power_table=_POWER_TABLE,
    )
    assert "EGFR" in prompt
    assert "sheet_flat" in prompt
    assert "domain III" in prompt  # abstract snippet
    for key in MENU_FEATURE_KEYS:
        assert key in prompt
    assert "JSON ONLY" in prompt
    assert "SIGNED" in prompt
    assert "NEVER reference experimental" in prompt
    # New: empirical power table + concentration instructions.
    assert _POWER_TABLE in prompt
    assert "DISCRIMINATIVE POWER" in prompt
    assert "AT MOST 12" in prompt
    assert "CONCENTRATE" in prompt


def test_build_prompt_power_table_section_skipped_when_empty():
    # Default empty table: no dangling/confusing empty power section, but the
    # concentration instructions still appear (they are unconditional).
    prompt = build_prior_prompt(
        "EGFR", _features_row(), _literature(), MENU_FEATURE_KEYS
    )
    assert "DISCRIMINATIVE POWER" not in prompt
    assert "AT MOST 12" in prompt
    assert "CONCENTRATE" in prompt


def test_build_prompt_defensive_on_missing_literature_keys():
    # Missing 'abstracts' / 'open_targets' must not crash.
    prompt = build_prior_prompt("EGFR", _features_row(), {}, MENU_FEATURE_KEYS)
    assert "EGFR" in prompt


# --- generate_prior ---------------------------------------------------------


_GOOD_PAYLOAD = {
    "weights": {"best_ipsae": 2.0, "bio__aggregation_propensity": -1.0},
    "failure_penalties": {"cysteine_fraction": {"gt": 0.08, "penalty": 1.0}},
    "epitope_residues": [355],
    "liabilities": ["aggregation"],
    "proposed_features": [{"name": "domain3_contacts",
                           "computable": "needs_structure"}],
    "rationale": "domain III",
    "citations": ["12345678"],
}


def test_generate_prior_with_fenced_json():
    fenced = "```json\n" + json.dumps(_GOOD_PAYLOAD) + "\n```"
    client = RecordedClient([fenced])
    prior = generate_prior("EGFR", _features_row(), _literature(),
                           MENU_FEATURE_KEYS, client)
    assert isinstance(prior, Prior)
    assert math.isclose(sum(abs(w) for w in prior.weights.values()), 1.0)
    assert prior.weights["bio__aggregation_propensity"] < 0
    assert prior.epitope_residues == [355]


def test_generate_prior_with_raw_json():
    client = RecordedClient([json.dumps(_GOOD_PAYLOAD)])
    prior = generate_prior("EGFR", _features_row(), _literature(),
                           MENU_FEATURE_KEYS, client)
    assert isinstance(prior, Prior)
    assert math.isclose(sum(abs(w) for w in prior.weights.values()), 1.0)


def test_generate_prior_threads_power_table_into_prompt():
    client = RecordedClient([json.dumps(_GOOD_PAYLOAD)])
    generate_prior(
        "EGFR", _features_row(), _literature(), MENU_FEATURE_KEYS, client,
        metric_power_table=_POWER_TABLE,
    )
    # The client saw exactly one prompt; it must carry the power table.
    assert len(client.prompts) == 1
    assert _POWER_TABLE in client.prompts[0]
    assert "DISCRIMINATIVE POWER" in client.prompts[0]


def test_generate_prior_unknown_key_raises():
    bad = dict(_GOOD_PAYLOAD, weights={"totally_made_up": 1.0})
    client = RecordedClient([json.dumps(bad)])
    with pytest.raises(ValueError, match="unknown metric key"):
        generate_prior("EGFR", _features_row(), _literature(),
                       MENU_FEATURE_KEYS, client)


def test_generate_prior_unparseable_raises():
    client = RecordedClient(["not json at all ((("])
    with pytest.raises(ValueError):
        generate_prior("EGFR", _features_row(), _literature(),
                       MENU_FEATURE_KEYS, client)


def test_generate_prior_with_prose_on_both_sides():
    fenced = (
        "Sure, here's the prior:\n```json\n"
        + json.dumps(_GOOD_PAYLOAD)
        + "\n```\nHope this helps!"
    )
    client = RecordedClient([fenced])
    prior = generate_prior("EGFR", _features_row(), _literature(),
                           MENU_FEATURE_KEYS, client)
    assert isinstance(prior, Prior)
    assert math.isclose(sum(abs(w) for w in prior.weights.values()), 1.0)
    assert prior.weights["bio__aggregation_propensity"] < 0
