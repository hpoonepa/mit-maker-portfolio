"""Tests for pc_contracts.leakage — RED phase first."""
import pytest
from pc_contracts.leakage import (
    EXPERIMENTAL_PREFIX,
    KNOWN_EXPERIMENTAL_COLUMNS,
    LeakageError,
    assert_no_leakage,
)


def test_experimental_prefix_value():
    assert EXPERIMENTAL_PREFIX == "experimental__"


def test_known_experimental_columns_is_frozenset():
    assert isinstance(KNOWN_EXPERIMENTAL_COLUMNS, frozenset)


def test_known_experimental_columns_contains_expected():
    expected = {
        "experimental__binding",
        "experimental__expressed",
        "experimental__expression_yield",
        "experimental__kd",
        "experimental__koff",
        "experimental__kon",
    }
    assert KNOWN_EXPERIMENTAL_COLUMNS == expected


def test_leakage_error_is_exception():
    err = LeakageError("test column")
    assert isinstance(err, Exception)


def test_assert_no_leakage_raises_on_known_experimental_column():
    with pytest.raises(LeakageError, match="experimental__binding"):
        assert_no_leakage(["computational__min_ipsae", "experimental__binding"])


def test_assert_no_leakage_raises_on_any_experimental_prefix():
    with pytest.raises(LeakageError):
        assert_no_leakage(["experimental__some_new_column"])


def test_assert_no_leakage_raises_and_names_offending_column():
    with pytest.raises(LeakageError, match="experimental__kd"):
        assert_no_leakage(["seq_length", "experimental__kd"])


def test_assert_no_leakage_passes_on_clean_set():
    # Should return None without raising
    result = assert_no_leakage(["computational__boltz2_min_ipsae", "seq_length"])
    assert result is None


def test_assert_no_leakage_passes_on_empty_set():
    result = assert_no_leakage([])
    assert result is None


def test_assert_no_leakage_raises_on_experimental_koff():
    with pytest.raises(LeakageError):
        assert_no_leakage(["computational__iptm", "experimental__koff"])


def test_assert_no_leakage_raises_on_experimental_kon():
    with pytest.raises(LeakageError):
        assert_no_leakage(["experimental__kon"])


def test_assert_no_leakage_passes_on_clean_generator():
    result = assert_no_leakage(c for c in ["computational__iptm", "seq_length"])
    assert result is None


def test_assert_no_leakage_raises_on_dirty_generator():
    with pytest.raises(LeakageError, match="experimental__kd"):
        assert_no_leakage(c for c in ["computational__iptm", "experimental__kd"])
