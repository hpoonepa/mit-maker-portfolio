"""Tests for pc_contracts.interfaces — RED phase first."""
import pytest
from pc_contracts.interfaces import (
    INTERFACE_CLASSES,
    TargetFeatures,
    DesignRow,
    LabelRow,
    MetricPrior,
    ScoredDesign,
)


# ── INTERFACE_CLASSES ──────────────────────────────────────────────────────────

def test_interface_classes_exact_values_and_order():
    assert INTERFACE_CLASSES == ("helical", "sheet_flat", "mixed", "ligand_present")


def test_interface_classes_is_tuple():
    assert isinstance(INTERFACE_CLASSES, tuple)


def test_interface_classes_length():
    assert len(INTERFACE_CLASSES) == 4


# ── TargetFeatures ─────────────────────────────────────────────────────────────

def _valid_target_features(**overrides):
    defaults = dict(
        target_id="tgt_001",
        pdb_id="5G51",
        chain="A",
        hotspots=[145, 148],
        log_length=5.2,
        disorder_fraction=0.1,
        frac_helix=0.4,
        frac_strand=0.2,
        frac_loop=0.4,
        epitope_planarity_rmsd=1.2,
        pocket_volume=300.0,
        druggability=0.8,
        epitope_hydrophobicity=0.3,
        epitope_net_charge=-1.0,
        frac_polar=0.35,
        interface_class="helical",
    )
    defaults.update(overrides)
    return TargetFeatures(**defaults)


def test_target_features_constructs_with_valid_args():
    tf = _valid_target_features()
    assert tf.target_id == "tgt_001"
    assert tf.pdb_id == "5G51"
    assert tf.chain == "A"
    assert tf.hotspots == [145, 148]
    assert tf.interface_class == "helical"


def test_target_features_optional_fields_can_be_none():
    tf = _valid_target_features(
        hotspots=None,
        epitope_planarity_rmsd=None,
        pocket_volume=None,
        druggability=None,
        epitope_hydrophobicity=None,
        epitope_net_charge=None,
    )
    assert tf.hotspots is None
    assert tf.epitope_planarity_rmsd is None


def test_target_features_invalid_interface_class_raises():
    with pytest.raises(ValueError, match="interface_class"):
        _valid_target_features(interface_class="pocket")


def test_target_features_empty_string_interface_class_raises():
    with pytest.raises(ValueError, match="interface_class"):
        _valid_target_features(interface_class="")


def test_target_features_all_valid_interface_classes_accepted():
    for cls in ("helical", "sheet_flat", "mixed", "ligand_present"):
        tf = _valid_target_features(interface_class=cls)
        assert tf.interface_class == cls


# ── DesignRow ──────────────────────────────────────────────────────────────────

def test_design_row_constructs_and_exposes_fields():
    dr = DesignRow(
        design_id="d_001",
        target_id="tgt_001",
        tool="rfdiffusion",
        tool_version="1.1.0",
        config_hash="abc123",
        seed=42,
        sequence="ACDEFGHIKLMNPQRSTVWY",
        metrics={"min_ipsae": 0.82, "iptm": 0.71},
        metric_blocks_present={"boltz2": True},
        cost_usd=0.05,
        wallclock_sec=120.0,
    )
    assert dr.design_id == "d_001"
    assert dr.metrics["min_ipsae"] == 0.82
    assert dr.metric_blocks_present["boltz2"] is True
    assert dr.seed == 42


# ── LabelRow ───────────────────────────────────────────────────────────────────

def test_label_row_constructs_and_exposes_fields():
    lr = LabelRow(
        design_id="d_001",
        target_id="tgt_001",
        sequence="ACDE",
        binds=True,
        binding_strength="strong",
        kd_nm=12.5,
        expressed=True,
        source="adaptyv_wetlab",
        license="CC-BY-4.0",
        provenance="experiment_2026_06",
        metric_blind_sampled=False,
    )
    assert lr.binds is True
    assert lr.kd_nm == 12.5
    assert lr.source == "adaptyv_wetlab"


def test_label_row_optional_fields_can_be_none():
    lr = LabelRow(
        design_id="d_002",
        target_id="tgt_001",
        sequence="ACDE",
        binds=None,
        binding_strength=None,
        kd_nm=None,
        expressed=None,
        source="adaptyv_wetlab",
        license="CC-BY-4.0",
        provenance="experiment_2026_06",
        metric_blind_sampled=True,
    )
    assert lr.binds is None
    assert lr.kd_nm is None


# ── MetricPrior ────────────────────────────────────────────────────────────────

def test_metric_prior_constructs_with_valid_source():
    for src in ("llm", "corrector", "global_default"):
        mp = MetricPrior(
            target_id="tgt_001",
            weights={"min_ipsae": 1.5},
            emphasized_metrics=["min_ipsae"],
            rationale="High AUC",
            source=src,
            confidence=0.9,
        )
        assert mp.source == src


def test_metric_prior_invalid_source_raises():
    with pytest.raises(ValueError, match="source"):
        MetricPrior(
            target_id="tgt_001",
            weights={},
            emphasized_metrics=[],
            rationale="test",
            source="bogus",
            confidence=0.5,
        )


def test_metric_prior_exposes_all_fields():
    mp = MetricPrior(
        target_id="tgt_001",
        weights={"min_ipsae": 2.0, "iptm": 1.0},
        emphasized_metrics=["min_ipsae"],
        rationale="Based on AUC study",
        source="llm",
        confidence=0.85,
    )
    assert mp.weights["min_ipsae"] == 2.0
    assert mp.emphasized_metrics == ["min_ipsae"]
    assert mp.confidence == 0.85


# ── ScoredDesign ───────────────────────────────────────────────────────────────

def test_scored_design_constructs_and_exposes_fields():
    sd = ScoredDesign(design_id="d_001", score=0.91, rank=1)
    assert sd.design_id == "d_001"
    assert sd.score == 0.91
    assert sd.rank == 1


def test_scored_design_is_frozen():
    from dataclasses import FrozenInstanceError
    sd = ScoredDesign(design_id="d_001", score=0.91, rank=1)
    with pytest.raises(FrozenInstanceError):
        sd.rank = 2
