"""Smoke tests: prove scorer/ can import and use shared contracts from pc_contracts."""
import dataclasses
import pytest

from pc_contracts import (
    TargetFeatures,
    MetricPrior,
    ScoredDesign,
    INTERFACE_CLASSES,
)


def _valid_target_features(**overrides) -> TargetFeatures:
    defaults = dict(
        target_id="target_5g51",
        pdb_id="5G51",
        chain="A",
        hotspots=[145, 148],
        log_length=4.2,
        disorder_fraction=0.05,
        frac_helix=0.60,
        frac_strand=0.10,
        frac_loop=0.30,
        epitope_planarity_rmsd=0.8,
        pocket_volume=1200.0,
        druggability=0.75,
        epitope_hydrophobicity=0.3,
        epitope_net_charge=-1.0,
        frac_polar=0.4,
        interface_class="helical",
    )
    defaults.update(overrides)
    return TargetFeatures(**defaults)


def test_target_features_construction_and_field():
    tf = _valid_target_features()
    assert tf.target_id == "target_5g51"
    assert tf.pdb_id == "5G51"
    assert tf.interface_class == "helical"
    assert tf.hotspots == [145, 148]


def test_target_features_valid_interface_classes_all_accepted():
    for cls in INTERFACE_CLASSES:
        tf = _valid_target_features(interface_class=cls)
        assert tf.interface_class == cls


def test_target_features_bogus_interface_class_raises_value_error():
    with pytest.raises(ValueError, match="interface_class"):
        _valid_target_features(interface_class="bogus")


def test_scored_design_is_frozen():
    sd = ScoredDesign(design_id="d001", score=0.92, rank=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        sd.score = 0.5  # type: ignore[misc]


def test_scored_design_fields():
    sd = ScoredDesign(design_id="d042", score=0.75, rank=3)
    assert sd.design_id == "d042"
    assert sd.score == pytest.approx(0.75)
    assert sd.rank == 3


def test_interface_classes_is_tuple_of_strings():
    assert isinstance(INTERFACE_CLASSES, tuple)
    assert all(isinstance(c, str) for c in INTERFACE_CLASSES)
    assert len(INTERFACE_CLASSES) >= 1
