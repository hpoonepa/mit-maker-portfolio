"""TDD tests for data/features.py — labeled FEATURE TABLE (Tracks 1+2).

Covers:
  - cheap sequence-feature math on the known sequence "ACDEFG" (hand-computed)
  - the bare key "boltz2_min_ipsae" is NEVER emitted as a header (must be canonical)
  - source ingest allowlist enforcement {overath, bindcraft, proteinbase}
  - one-row-per-deduped-design output with the expected LOCKED v1 columns
"""
import math

import pytest

from data import features


# --------------------------------------------------------------------------
# TIER 3 — cheap sequence features. Hand-computed for "ACDEFG".
# Average residue masses (monomer minus water):
#   A=71.0788 C=103.1388 D=115.0886 E=129.1155 F=147.1766 G=57.0519
#   sum residues = 622.6502 ; +water(18.01528) = 640.66548
# --------------------------------------------------------------------------
SEQ = "ACDEFG"


def test_seq_length():
    assert features.seq_length(SEQ) == 6


def test_molecular_weight_acdefg():
    assert features.molecular_weight(SEQ) == pytest.approx(640.66548, abs=1e-3)


def test_cysteine_fraction_acdefg():
    # one C out of six residues
    assert features.cysteine_fraction(SEQ) == pytest.approx(1 / 6)


def test_hydrophobic_fraction_acdefg():
    # hydrophobic set AILMFWVP -> A and F match => 2/6
    assert features.hydrophobic_fraction(SEQ) == pytest.approx(2 / 6)


def test_aromatic_fraction_acdefg():
    # aromatic set FWY -> only F => 1/6
    assert features.aromatic_fraction(SEQ) == pytest.approx(1 / 6)


def test_net_charge_ph7_acdefg():
    # (K+R) - (D+E) = 0 - 2 = -2
    assert features.net_charge_ph7(SEQ) == pytest.approx(-2.0)


def test_isoelectric_point_acidic_sequence_below_7():
    # ACDEFG has 2 acidic, 0 basic residues -> acidic protein, pI must be < 7
    pi = features.isoelectric_point(SEQ)
    assert pi < 7.0
    assert 0.0 < pi < 14.0


def test_empty_sequence_features_are_safe():
    assert features.seq_length("") == 0
    assert features.cysteine_fraction("") == 0.0
    assert features.hydrophobic_fraction("") == 0.0
    assert features.aromatic_fraction("") == 0.0
    assert features.net_charge_ph7("") == 0.0


# --------------------------------------------------------------------------
# Header / canonicalization discipline
# --------------------------------------------------------------------------
def test_bare_boltz2_min_ipsae_is_never_a_header():
    headers = features.feature_table_columns()
    assert "boltz2_min_ipsae" not in headers
    assert "computational__boltz2_min_ipsae" in headers


def test_every_metric_header_is_canonical_prefixed():
    # Any header that is a metric (not an identity/label/sequence-feature column)
    # must carry a canonical prefix. We check the locked metric names specifically.
    headers = features.feature_table_columns()
    for bare in (
        "boltz2_min_ipsae",
        "boltz2_lis",
        "boltz2_iptm",
        "proteinmpnn_score",
        "esmfold_plddt",
        "interface_residues",
        "boltz2_complex_iplddt",
    ):
        assert bare not in headers, f"bare metric {bare!r} leaked into headers"


def test_expected_locked_columns_present():
    headers = set(features.feature_table_columns())
    expected = {
        "source", "target", "sequence", "binds", "assay", "license", "was_tested",
        "computational__boltz2_min_ipsae",
        "ipsae_min_native", "ipsae_source",
        "shape_complementarity", "rmsd_binder",
        "computational__boltz2_lis",
        "seq_length", "molecular_weight", "isoelectric_point",
        "cysteine_fraction", "hydrophobic_fraction", "aromatic_fraction",
        "net_charge_ph7",
    }
    missing = expected - headers
    assert not missing, f"missing locked columns: {sorted(missing)}"


# --------------------------------------------------------------------------
# Ingest allowlist
# --------------------------------------------------------------------------
def test_build_rows_rejects_source_outside_allowlist():
    bad = [{"source": "rosetta", "target": "EGFR", "sequence": "ACDEFG", "binds": True}]
    with pytest.raises(AssertionError):
        features.build_feature_rows(bad)


def test_build_rows_accepts_allowlisted_sources():
    good = [{"source": "overath", "target": "EGFR", "sequence": "ACDEFG", "binds": True}]
    rows = features.build_feature_rows(good)
    assert len(rows) == 1


# --------------------------------------------------------------------------
# One row per deduped design, with sequence features computed and was_tested=1
# --------------------------------------------------------------------------
def test_one_row_per_design_with_computed_features_and_was_tested():
    deduped = [
        {"source": "overath", "target": "EGFR", "sequence": "ACDEFG", "binds": True},
        {"source": "bindcraft", "target": "PDL1", "sequence": "GGGGCC", "binds": False},
    ]
    rows = features.build_feature_rows(deduped)
    assert len(rows) == 2
    by_seq = {r["sequence"]: r for r in rows}

    acd = by_seq["ACDEFG"]
    assert acd["source"] == "overath"
    assert acd["target"] == "EGFR"
    assert acd["binds"] is True
    assert acd["was_tested"] == 1
    assert acd["seq_length"] == 6
    assert float(acd["net_charge_ph7"]) == pytest.approx(-2.0)
    assert acd["license"] == "open"
    # overath assay = source name
    assert acd["assay"] == "overath"
    # overath/bindcraft have no native boltz2_min_ipsae -> empty
    assert acd["computational__boltz2_min_ipsae"] == ""


def test_proteinbase_nipah_license_is_unclear():
    deduped = [
        {"source": "proteinbase", "target": "NIPAH", "sequence": "ACDEFG", "binds": True},
        {"source": "proteinbase", "target": "EGFR", "sequence": "GGGGCC", "binds": True},
    ]
    rows = features.build_feature_rows(deduped)
    by_seq = {r["sequence"]: r for r in rows}
    assert by_seq["ACDEFG"]["license"] == "unclear"   # Nipah target
    assert by_seq["GGGGCC"]["license"] == "open"       # non-Nipah


def test_native_metrics_threaded_through_when_present():
    # a deduped record may carry pre-parsed native metric values
    deduped = [{
        "source": "overath", "target": "EGFR", "sequence": "ACDEFG", "binds": True,
        "ipsae_min_native": 0.42, "ipsae_source": "boltz1",
        "computational__boltz2_iptm": 0.7,
    }]
    rows = features.build_feature_rows(deduped)
    r = rows[0]
    assert float(r["ipsae_min_native"]) == pytest.approx(0.42)
    assert r["ipsae_source"] == "boltz1"
    assert float(r["computational__boltz2_iptm"]) == pytest.approx(0.7)
