"""Tests for pc_contracts.labels — RED phase first."""
from pc_contracts.labels import SILICO_LABEL_MARKERS, is_real_label


def test_silico_label_markers_is_frozenset():
    assert isinstance(SILICO_LABEL_MARKERS, frozenset)


def test_silico_label_markers_contains_expected():
    expected = {
        "ipsae", "dockq", "ptmenergy", "boltz2",
        "hit_rule", "in_silico", "predicted", "protenix",
    }
    assert SILICO_LABEL_MARKERS == expected


# ── is_real_label True cases ───────────────────────────────────────────────────

def test_adaptyv_wetlab_is_real():
    assert is_real_label("adaptyv_wetlab") is True


def test_cao_2022_facs_is_real():
    assert is_real_label("cao_2022_facs") is True


def test_arbitrary_wetlab_source_is_real():
    assert is_real_label("mit_2024_spr_assay") is True


# ── is_real_label False cases ──────────────────────────────────────────────────

def test_empty_string_is_not_real():
    assert is_real_label("") is False


def test_none_is_not_real():
    assert is_real_label(None) is False


def test_whitespace_only_is_not_real():
    assert is_real_label("   ") is False


def test_ipsae_threshold_is_not_real():
    assert is_real_label("ipsae_threshold") is False


def test_boltz2_hit_rule_is_not_real():
    assert is_real_label("boltz2_hit_rule") is False


def test_dockq_cutoff_is_not_real():
    assert is_real_label("dockq_cutoff") is False


def test_in_silico_screening_is_not_real():
    assert is_real_label("in_silico_screening") is False


def test_predicted_binding_is_not_real():
    assert is_real_label("predicted_binding") is False


def test_protenix_score_is_not_real():
    assert is_real_label("protenix_score") is False


def test_ptmenergy_filter_is_not_real():
    assert is_real_label("ptmenergy_filter") is False


def test_hit_rule_is_not_real():
    assert is_real_label("hit_rule") is False


def test_case_insensitive_marker_detection():
    # "BOLTZ2" uppercased in source should still be caught
    assert is_real_label("BOLTZ2_hit") is False


def test_partial_match_in_longer_source():
    # source containing "ipsae" anywhere should be rejected
    assert is_real_label("custom_ipsae_based_scorer") is False
