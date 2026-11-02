"""Smoke tests: prove data/ can import and use shared contracts from pc_contracts."""
import pytest
import dataclasses

from pc_contracts import (
    DesignRow,
    LabelRow,
    canonical_metric_key,
    assert_no_leakage,
    LeakageError,
    is_real_label,
)


def test_label_row_construction_and_field():
    row = LabelRow(
        design_id="design_001",
        target_id="target_5g51",
        sequence="ACDEFGHIKLMNPQRSTVWY",
        binds=True,
        binding_strength="strong",
        kd_nm=12.5,
        expressed=True,
        source="SPR_assay",
        license="CC-BY-4.0",
        provenance="lab_A/2026-06",
        metric_blind_sampled=False,
    )
    assert row.design_id == "design_001"
    assert row.target_id == "target_5g51"
    assert row.binds is True
    assert row.kd_nm == pytest.approx(12.5)
    assert row.metric_blind_sampled is False


def test_canonical_metric_key_prefixes_bare_name():
    assert canonical_metric_key("boltz2_min_ipsae") == "computational__boltz2_min_ipsae"


def test_assert_no_leakage_raises_leakage_error_on_experimental_column():
    with pytest.raises(LeakageError):
        assert_no_leakage(["experimental__kd"])


def test_is_real_label_returns_false_for_silico_source():
    # "boltz2" is a SILICO_LABEL_MARKER — not a real wet-lab label
    assert is_real_label("boltz2_prediction") is False


def test_is_real_label_returns_true_for_real_assay():
    assert is_real_label("SPR_assay") is True
