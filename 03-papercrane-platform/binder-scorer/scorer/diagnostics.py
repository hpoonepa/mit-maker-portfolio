"""diagnostics.py — Selection-bias diagnostics (Task A7).

Inverse-propensity weighting (IPW). The labeled designs we have are not a
random sample of all designs ever generated — they were selected for wet-lab
testing, often *because* a computational scorer liked them. That selection
("was_tested") is the propensity. To estimate what the scorer delta would be on
the full design population, we up-weight rarely-tested designs (low propensity)
and down-weight heavily-tested ones, then take the weighted mean of the deltas.

The full was_tested-AUC decomposition (estimating the propensity model and the
counterfactual delta on never-tested negatives) is a documented STUB below: it
is pending real untested-design negatives in the feature table, which do not yet
exist. ``ipw_delta`` itself is fully implemented and unit-tested.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

_P_LO = 0.01
_P_HI = 0.99


def ipw_delta(
    scorer_deltas: Sequence[float], propensity_scores: Sequence[float]
) -> float:
    """Inverse-propensity-weighted mean of per-design scorer deltas.

    p is clipped to [0.01, 0.99]; weights = 1/p normalized to sum to 1; returns
    the weighted mean. Returns nan on empty input. Raises ValueError on length
    mismatch.
    """
    d = np.asarray(list(scorer_deltas), dtype=float)
    p = np.asarray(list(propensity_scores), dtype=float)
    if len(d) != len(p):
        raise ValueError(
            f"scorer_deltas (n={len(d)}) and propensity_scores (n={len(p)}) "
            "must have equal length"
        )
    if len(d) == 0:
        return float("nan")
    p = np.clip(p, _P_LO, _P_HI)
    w = 1.0 / p
    w = w / w.sum()
    return float(np.sum(w * d))


def was_tested_auc_decomposition(*_args, **_kwargs):  # pragma: no cover - stub
    """STUB (pending real untested-design negatives).

    Intended decomposition: fit a propensity model P(was_tested | features),
    measure its AUC (how predictable testing is), then re-estimate the scorer
    delta on the implied never-tested population via IPW (using ``ipw_delta``).
    Cannot be computed until the feature table contains generated-but-never-
    tested designs to serve as the untested negatives. Raises until then.
    """
    raise NotImplementedError(
        "was_tested-AUC decomposition pending real untested-design negatives"
    )
