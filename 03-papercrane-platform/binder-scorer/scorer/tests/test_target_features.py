"""Tests for scorer.target_features — sequence-based target-side feature math.

Expected values are hand-computed on a known 20-residue test sequence
(one of each canonical amino acid: ACDEFGHIKLMNPQRSTVWY) using the standard
Kyte-Doolittle hydropathy and Chou-Fasman propensity tables.
"""

from __future__ import annotations

import math

import pytest

from scorer.target_features import (
    compute_target_features,
    interface_class,
)

# One of each canonical amino acid, 20 residues.
ONE_EACH = "ACDEFGHIKLMNPQRSTVWY"


def test_log_length():
    f = compute_target_features(ONE_EACH)
    assert f["log_length"] == pytest.approx(math.log(20))


def test_frac_polar():
    # STNQCYHKRDE present: S,T,N,Q,C,Y,H,K,R,D,E = 11 of 20
    f = compute_target_features(ONE_EACH)
    assert f["frac_polar"] == pytest.approx(0.55)


def test_hydrophobic_fraction():
    # AILMFWVP present: A,I,L,M,F,W,V,P = 8 of 20
    f = compute_target_features(ONE_EACH)
    assert f["hydrophobic_fraction"] == pytest.approx(0.40)


def test_aromatic_fraction():
    # FWY = 3 of 20
    f = compute_target_features(ONE_EACH)
    assert f["aromatic_fraction"] == pytest.approx(0.15)


def test_epitope_net_charge():
    # (K+R - D-E)/n = (1+1-1-1)/20 = 0
    f = compute_target_features(ONE_EACH)
    assert f["epitope_net_charge"] == pytest.approx(0.0)


def test_epitope_hydrophobicity():
    f = compute_target_features(ONE_EACH)
    assert f["epitope_hydrophobicity"] == pytest.approx(-0.49)


def test_secondary_structure_fractions():
    f = compute_target_features(ONE_EACH)
    assert f["frac_helix"] == pytest.approx(0.30)
    assert f["frac_strand"] == pytest.approx(0.40)
    assert f["frac_loop"] == pytest.approx(0.30)


def test_ss_fractions_sum_to_one():
    f = compute_target_features(ONE_EACH)
    total = f["frac_helix"] + f["frac_strand"] + f["frac_loop"]
    assert total == pytest.approx(1.0)


def test_disorder_fraction():
    # SPEKQGRDAN present: S,P,E,K,Q,G,R,D,A,N = 10 of 20
    f = compute_target_features(ONE_EACH)
    assert f["disorder_fraction"] == pytest.approx(0.5)


def test_pocket_and_druggability_are_nan():
    f = compute_target_features(ONE_EACH)
    assert math.isnan(f["pocket_volume"])
    assert math.isnan(f["druggability"])


def test_interface_class_keys_present():
    f = compute_target_features(ONE_EACH)
    assert "interface_class" in f
    assert f["interface_class"] in ("helical", "sheet_flat", "mixed")


# --- interface_class classification (pure logic) ---


def test_interface_class_helical():
    # frac_helix >= 0.45 and helix > strand
    assert interface_class(0.50, 0.20, 0.30) == "helical"


def test_interface_class_sheet_flat():
    # frac_strand >= 0.35 and strand > helix
    assert interface_class(0.20, 0.40, 0.40) == "sheet_flat"


def test_interface_class_mixed():
    # neither helical nor sheet thresholds met
    assert interface_class(0.30, 0.30, 0.40) == "mixed"


def test_interface_class_helix_ties_threshold_but_not_dominant():
    # helix == strand -> not helical (needs strict helix > strand); strand 0.45
    # >= 0.35 and strand > helix is False (equal) -> mixed
    assert interface_class(0.45, 0.45, 0.10) == "mixed"


def test_interface_class_high_helix_below_threshold_is_mixed():
    # helix 0.40 < 0.45 -> not helical; strand 0.30 < 0.35 -> not sheet -> mixed
    assert interface_class(0.40, 0.30, 0.30) == "mixed"


def test_lowercase_and_whitespace_tolerated():
    f = compute_target_features("  acdefghiklmnpqrstvwy  ")
    assert f["log_length"] == pytest.approx(math.log(20))
