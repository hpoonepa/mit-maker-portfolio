"""Tests for pc_contracts.metrics — RED phase first."""
from pc_contracts.metrics import (
    CANONICAL_PREFIX,
    CANONICAL_MIN_IPSAE,
    canonical_metric_key,
)


def test_canonical_prefix_value():
    assert CANONICAL_PREFIX == "computational__"


def test_canonical_min_ipsae_value():
    assert CANONICAL_MIN_IPSAE == "computational__boltz2_min_ipsae"


def test_bare_name_gets_prefixed():
    assert canonical_metric_key("min_ipsae") == "computational__min_ipsae"


def test_already_computational_prefix_unchanged():
    key = "computational__boltz2_min_ipsae"
    assert canonical_metric_key(key) == key


def test_experimental_prefix_unchanged():
    key = "experimental__binding"
    assert canonical_metric_key(key) == key


def test_idempotent_on_bare_name():
    result = canonical_metric_key("iptm")
    assert canonical_metric_key(result) == result


def test_idempotent_on_already_prefixed():
    key = "computational__seq_length"
    assert canonical_metric_key(canonical_metric_key(key)) == canonical_metric_key(key)


def test_idempotent_on_experimental():
    key = "experimental__kd"
    assert canonical_metric_key(canonical_metric_key(key)) == canonical_metric_key(key)


def test_seq_length_bare_gets_prefixed():
    assert canonical_metric_key("seq_length") == "computational__seq_length"


def test_empty_string_gets_bare_prefix():
    # Documents current behavior: "" is treated as a bare name.
    assert canonical_metric_key("") == "computational__"


def test_experimental_prefix_constant_reused_from_leakage():
    # metrics must reuse leakage.EXPERIMENTAL_PREFIX, not redefine it.
    from pc_contracts.leakage import EXPERIMENTAL_PREFIX
    assert canonical_metric_key(EXPERIMENTAL_PREFIX + "binding") == "experimental__binding"
