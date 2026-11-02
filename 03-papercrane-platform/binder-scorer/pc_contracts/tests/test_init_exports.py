"""Tests that __init__.py re-exports all required public names."""
import pc_contracts


def test_interface_classes_exported():
    assert hasattr(pc_contracts, "INTERFACE_CLASSES")


def test_target_features_exported():
    assert hasattr(pc_contracts, "TargetFeatures")


def test_design_row_exported():
    assert hasattr(pc_contracts, "DesignRow")


def test_label_row_exported():
    assert hasattr(pc_contracts, "LabelRow")


def test_metric_prior_exported():
    assert hasattr(pc_contracts, "MetricPrior")


def test_scored_design_exported():
    assert hasattr(pc_contracts, "ScoredDesign")


def test_canonical_metric_key_exported():
    assert hasattr(pc_contracts, "canonical_metric_key")
    assert callable(pc_contracts.canonical_metric_key)


def test_canonical_prefix_exported():
    assert hasattr(pc_contracts, "CANONICAL_PREFIX")


def test_canonical_min_ipsae_exported():
    assert hasattr(pc_contracts, "CANONICAL_MIN_IPSAE")


def test_experimental_prefix_exported():
    assert hasattr(pc_contracts, "EXPERIMENTAL_PREFIX")


def test_known_experimental_columns_exported():
    assert hasattr(pc_contracts, "KNOWN_EXPERIMENTAL_COLUMNS")


def test_leakage_error_exported():
    assert hasattr(pc_contracts, "LeakageError")
    assert issubclass(pc_contracts.LeakageError, Exception)


def test_assert_no_leakage_exported():
    assert hasattr(pc_contracts, "assert_no_leakage")
    assert callable(pc_contracts.assert_no_leakage)


def test_silico_label_markers_exported():
    assert hasattr(pc_contracts, "SILICO_LABEL_MARKERS")


def test_is_real_label_exported():
    assert hasattr(pc_contracts, "is_real_label")
    assert callable(pc_contracts.is_real_label)


def test_is_real_label_callable_through_package():
    # Actually invoke it via the package namespace, not just hasattr.
    assert pc_contracts.is_real_label("adaptyv_wetlab") is True
    assert pc_contracts.is_real_label("boltz2_hit_rule") is False
