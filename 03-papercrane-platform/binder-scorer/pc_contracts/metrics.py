"""Canonical metric-key helpers — fixes cross-package naming drift."""
# Dependency is one-directional: metrics -> leakage. leakage imports nothing
# from metrics, so reusing EXPERIMENTAL_PREFIX here cannot create an import cycle.
# This is the whole point of pc_contracts: one constant, not two drifting copies.
from pc_contracts.leakage import EXPERIMENTAL_PREFIX

CANONICAL_PREFIX = "computational__"
CANONICAL_MIN_IPSAE = "computational__boltz2_min_ipsae"

_KNOWN_PREFIXES = (CANONICAL_PREFIX, EXPERIMENTAL_PREFIX)


def canonical_metric_key(name: str) -> str:
    """Return the canonical metric key for *name*.

    - Already prefixed with ``computational__`` or ``experimental__`` → unchanged.
    - Bare name → ``computational__<name>``.
    - Idempotent: calling twice returns same result as calling once.
    """
    for prefix in _KNOWN_PREFIXES:
        if name.startswith(prefix):
            return name
    return CANONICAL_PREFIX + name
