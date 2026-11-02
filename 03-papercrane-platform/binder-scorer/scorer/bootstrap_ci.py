"""bootstrap_ci.py — Target-clustered paired BCa bootstrap CI (Task A6).

The unit of resampling is the TARGET fold (not the individual design). Each
element of ``per_target_deltas`` is one well-powered target's
(candidate - baseline) delta on the primary endpoint. We resample those target
deltas with replacement to form a target-clustered confidence interval for the
mean delta, which correctly propagates the small-n (n~11) target-level
uncertainty rather than the much larger design-level n.

Interval method: BCa (bias-corrected and accelerated) percentile bootstrap.
  - bias-correction z0 from the fraction of bootstrap means below the observed.
  - acceleration a from jackknife skewness of the target deltas.
If the BCa adjustment degenerates (e.g. all bootstrap means identical, or
z0/a non-finite), we fall back cleanly to the plain percentile interval. This
keeps the estimator robust on tiny/degenerate fold sets while remaining BCa in
the normal case.

Also returned: a one-sided sign test (binomial, H1: median delta > 0) and a
one-sided Wilcoxon signed-rank p (alternative="greater") when n>=10, else nan.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import stats

_ALPHA = 0.05  # 95% CI
_Z_LO = stats.norm.ppf(_ALPHA / 2)
_Z_HI = stats.norm.ppf(1 - _ALPHA / 2)


def _percentile_ci(boot_means: np.ndarray) -> tuple[float, float]:
    lo = float(np.percentile(boot_means, 100 * (_ALPHA / 2)))
    hi = float(np.percentile(boot_means, 100 * (1 - _ALPHA / 2)))
    return lo, hi


def _bca_ci(deltas: np.ndarray, boot_means: np.ndarray, point: float) -> tuple[float, float]:
    n = len(deltas)
    # bias-correction z0
    prop_below = float(np.mean(boot_means < point))
    if prop_below <= 0.0 or prop_below >= 1.0:
        return _percentile_ci(boot_means)
    z0 = stats.norm.ppf(prop_below)

    # acceleration via jackknife
    jack = np.array([np.mean(np.delete(deltas, i)) for i in range(n)])
    jack_mean = jack.mean()
    diffs = jack_mean - jack
    denom = 6.0 * (np.sum(diffs**2) ** 1.5)
    if denom == 0.0:
        return _percentile_ci(boot_means)
    a = float(np.sum(diffs**3) / denom)

    if not (math.isfinite(z0) and math.isfinite(a)):
        return _percentile_ci(boot_means)

    def _adj(z):
        denom2 = 1 - a * (z0 + z)
        if denom2 == 0:
            return None
        return stats.norm.cdf(z0 + (z0 + z) / denom2)

    p_lo = _adj(_Z_LO)
    p_hi = _adj(_Z_HI)
    if p_lo is None or p_hi is None:
        return _percentile_ci(boot_means)
    lo = float(np.percentile(boot_means, 100 * p_lo))
    hi = float(np.percentile(boot_means, 100 * p_hi))
    return lo, hi


def paired_bca_ci(
    per_target_deltas: Sequence[float], n_boot: int = 10000, seed: int = 0
) -> dict:
    """Target-clustered paired BCa bootstrap of the mean delta.

    Returns dict with: point, lo, hi, n, n_positive_deltas, sign_test_p,
    wilcoxon_p.
    """
    deltas = np.asarray(list(per_target_deltas), dtype=float)
    n = len(deltas)
    point = float(np.mean(deltas)) if n else float("nan")
    n_pos = int(np.sum(deltas > 0))

    if n == 0:
        return {
            "point": float("nan"), "lo": float("nan"), "hi": float("nan"),
            "n": 0, "n_positive_deltas": 0,
            "sign_test_p": float("nan"), "wilcoxon_p": float("nan"),
        }

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = deltas[idx].mean(axis=1)

    if np.all(boot_means == boot_means[0]):
        lo = hi = float(boot_means[0])
    else:
        lo, hi = _bca_ci(deltas, boot_means, point)

    # one-sided sign test (H1: P(delta>0) > 0.5), ties excluded
    n_nonzero = int(np.sum(deltas != 0))
    if n_nonzero == 0:
        sign_p = 1.0
    else:
        sign_p = float(
            stats.binomtest(n_pos, n_nonzero, 0.5, alternative="greater").pvalue
        )

    if n >= 10 and not np.all(deltas == 0):
        try:
            wilcoxon_p = float(stats.wilcoxon(deltas, alternative="greater").pvalue)
        except ValueError:
            wilcoxon_p = float("nan")
    else:
        wilcoxon_p = float("nan")

    return {
        "point": point, "lo": lo, "hi": hi, "n": n,
        "n_positive_deltas": n_pos,
        "sign_test_p": sign_p, "wilcoxon_p": wilcoxon_p,
    }
