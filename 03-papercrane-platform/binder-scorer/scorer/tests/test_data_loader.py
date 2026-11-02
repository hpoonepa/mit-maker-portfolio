from __future__ import annotations

import math

import pytest

from scorer.data_loader import (
    LGBM_FEATURE_KEYS,
    OVERATH_FEATURE_KEYS,
    load_designs,
    parse_binds,
    synth_design_id,
)


def test_parse_binds_string_true_false():
    assert parse_binds("True") is True
    assert parse_binds("False") is False
    assert parse_binds(True) is True
    assert parse_binds("") is False
    assert parse_binds("nan") is False


def test_synth_design_id_stable_and_target_prefixed():
    a = synth_design_id("EGFR", "ACDEFG")
    b = synth_design_id("EGFR", "ACDEFG")
    assert a == b
    assert a.startswith("EGFR:")
    assert a != synth_design_id("EGFR", "ACDEFH")


def test_best_ipsae_prefers_boltz2_then_native(tmp_path):
    csv = tmp_path / "f.csv"
    csv.write_text(
        "target,sequence,binds,computational__boltz2_min_ipsae,ipsae_min_native,"
        "shape_complementarity,rmsd_binder,computational__boltz2_iptm,"
        "computational__boltz2_lis,computational__actifptm,"
        "computational__interface_residues,computational__boltz2_complex_iplddt,"
        "computational__proteinmpnn_score,computational__esmfold_plddt,"
        "seq_length,molecular_weight,isoelectric_point,cysteine_fraction,"
        "hydrophobic_fraction,aromatic_fraction,net_charge_ph7\n"
        # row 1: has boltz2 -> best_ipsae = 0.8
        "T,AAAA,True,0.8,0.3,0.6,1.2,0.7,5,0.5,10,80,-1.0,85,4,400,6.5,0.0,0.4,0.1,1.0\n"
        # row 2: no boltz2 -> best_ipsae = native 0.6
        "T,CCCC,False,,0.6,0.5,2.0,0.6,4,0.4,8,70,-1.5,80,4,420,6.0,0.0,0.3,0.05,-1.0\n"
        # row 3: neither -> best_ipsae NaN
        "T,GGGG,False,,,0.4,3.0,0.5,3,0.3,6,60,-2.0,75,4,410,5.5,0.0,0.2,0.0,0.0\n"
    )
    designs = load_designs(str(csv))
    by_seq = {d["sequence"]: d for d in designs}
    assert by_seq["AAAA"]["best_ipsae"] == pytest.approx(0.8)
    assert by_seq["CCCC"]["best_ipsae"] == pytest.approx(0.6)
    assert math.isnan(by_seq["GGGG"]["best_ipsae"])
    # binds parsed to bool
    assert by_seq["AAAA"]["binds"] is True
    assert by_seq["CCCC"]["binds"] is False
    # design_id present + unique
    ids = {d["design_id"] for d in designs}
    assert len(ids) == 3


def test_missing_metric_cells_become_nan(tmp_path):
    csv = tmp_path / "f.csv"
    header = (
        "target,sequence,binds,computational__boltz2_min_ipsae,ipsae_min_native,"
        "shape_complementarity,rmsd_binder,computational__boltz2_iptm,"
        "computational__boltz2_lis,computational__actifptm,"
        "computational__interface_residues,computational__boltz2_complex_iplddt,"
        "computational__proteinmpnn_score,computational__esmfold_plddt,"
        "seq_length,molecular_weight,isoelectric_point,cysteine_fraction,"
        "hydrophobic_fraction,aromatic_fraction,net_charge_ph7\n"
    )
    csv.write_text(
        header
        + "T,AAAA,True,0.8,,,,,,,,,,,4,400,6.5,0.0,0.4,0.1,1.0\n"
    )
    d = load_designs(str(csv))[0]
    assert math.isnan(d["features"]["shape_complementarity"])
    assert math.isnan(d["features"]["computational__boltz2_iptm"])


_BIO_KEYS = (
    "bio__aggregation_propensity",
    "bio__ptm_site_density",
    "bio__phospho_site_density",
    "bio__disulfide_potential",
    "bio__disorder_fraction",
    "bio__topology_helix_frac",
    "bio__topology_strand_frac",
    "bio__topology_loop_frac",
    "bio__immunogenicity_proxy",
)


def test_bio_columns_loaded_into_features(tmp_path):
    csv = tmp_path / "bio.csv"
    csv.write_text(
        "target,sequence,binds,computational__boltz2_min_ipsae,"
        "bio__aggregation_propensity,bio__disorder_fraction\n"
        "T,AAAA,True,0.8,0.42,0.15\n"
    )
    d = load_designs(str(csv))[0]
    assert d["features"]["bio__aggregation_propensity"] == pytest.approx(0.42)
    assert d["features"]["bio__disorder_fraction"] == pytest.approx(0.15)


def test_bio_columns_missing_value_becomes_nan(tmp_path):
    csv = tmp_path / "bio.csv"
    csv.write_text(
        "target,sequence,binds,bio__aggregation_propensity\n"
        "T,AAAA,True,\n"
    )
    d = load_designs(str(csv))[0]
    assert math.isnan(d["features"]["bio__aggregation_propensity"])


def test_no_bio_columns_means_no_bio_keys(tmp_path):
    csv = tmp_path / "nobio.csv"
    csv.write_text(
        "target,sequence,binds,computational__boltz2_min_ipsae\n"
        "T,AAAA,True,0.8\n"
    )
    d = load_designs(str(csv))[0]
    assert not any(k.startswith("bio__") for k in d["features"])


def test_real_bio_csv_loads_nine_bio_keys():
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "data", "processed", "labeled_features_bio.csv",
    )
    if not os.path.exists(path):
        pytest.skip("real bio CSV not present")
    designs = load_designs(path)
    assert designs
    feats = designs[0]["features"]
    for k in _BIO_KEYS:
        assert k in feats


def test_feature_key_sets_well_formed():
    assert "best_ipsae" in LGBM_FEATURE_KEYS
    assert OVERATH_FEATURE_KEYS == ("best_ipsae", "shape_complementarity", "rmsd_binder")
    # the lgbm set should include sequence features
    assert "molecular_weight" in LGBM_FEATURE_KEYS
    assert "net_charge_ph7" in LGBM_FEATURE_KEYS
