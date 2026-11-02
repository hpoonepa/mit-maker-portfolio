"""Circular-label ban — ensures binding labels come from physical assays only."""
from typing import Optional

SILICO_LABEL_MARKERS: frozenset[str] = frozenset({
    "ipsae",
    "dockq",
    "ptmenergy",
    "boltz2",
    "hit_rule",
    "in_silico",
    "predicted",
    "protenix",
})


def is_real_label(source: Optional[str]) -> bool:
    """Return True iff *source* represents a genuine wet-lab / experimental assay.

    Returns False when:
    - *source* is ``None``, empty, or whitespace-only.
    - The lowercased *source* contains any marker from :data:`SILICO_LABEL_MARKERS`,
      indicating the label was derived from in-silico predictions rather than
      a real physical measurement.
    """
    if not source or not source.strip():
        return False
    lowered = source.lower()
    return not any(marker in lowered for marker in SILICO_LABEL_MARKERS)
