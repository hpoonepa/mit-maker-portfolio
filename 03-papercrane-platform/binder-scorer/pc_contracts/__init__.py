"""pc_contracts — shared contracts for the Paper Crane binder-scorer pipeline.

Single source of truth for types, metric naming, leakage guards, and label
integrity rails.  Both ``data/`` and ``scorer/`` import from here; this is what
prevents the cross-package type-drift bug.
"""
from pc_contracts.interfaces import (
    INTERFACE_CLASSES,
    DesignRow,
    LabelRow,
    MetricPrior,
    ScoredDesign,
    TargetFeatures,
)
from pc_contracts.labels import SILICO_LABEL_MARKERS, is_real_label
from pc_contracts.leakage import (
    EXPERIMENTAL_PREFIX,
    KNOWN_EXPERIMENTAL_COLUMNS,
    LeakageError,
    assert_no_leakage,
)
from pc_contracts.metrics import (
    CANONICAL_MIN_IPSAE,
    CANONICAL_PREFIX,
    canonical_metric_key,
)

__all__ = [
    # interfaces
    "INTERFACE_CLASSES",
    "TargetFeatures",
    "DesignRow",
    "LabelRow",
    "MetricPrior",
    "ScoredDesign",
    # metrics
    "canonical_metric_key",
    "CANONICAL_PREFIX",
    "CANONICAL_MIN_IPSAE",
    # leakage
    "EXPERIMENTAL_PREFIX",
    "KNOWN_EXPERIMENTAL_COLUMNS",
    "LeakageError",
    "assert_no_leakage",
    # labels
    "SILICO_LABEL_MARKERS",
    "is_real_label",
]
