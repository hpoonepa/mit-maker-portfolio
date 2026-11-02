# SPDX-License-Identifier: MIT
"""Cluster-clustered paired bootstrap, macro-averaging, and power statements.

Three ideas, all of them about not fooling ourselves:

1. **The unit of resampling is the antigen cluster, not the instance.** Two
   antibody complexes of the same antigen are not independent observations.
   Resampling instances would quote an interval built from an n of 16,800 when
   the real n is ~2,050 antigens, and would make a null result look
   significant.
2. **Macro-averaging by cluster is the default, not an option.** SARS-CoV-2
   spike alone is 2,871 of 16,701 instances (17%, spec section 4.2), so an
   unstratified micro-average is a statement about one glycoprotein. The
   micro-average is still available, behind an explicit flag, because it is
   the right number when you genuinely want per-instance incidence.
3. **An effect smaller than the minimum detectable effect is untested, not
   disproven.** :func:`power_statement` says so in those words.

Provenance
----------
:func:`paired_bca_ci` and its private helpers are ported from
``scorer/bootstrap_ci.py``, and :data:`PREREGISTERED_MDE`,
:func:`compute_mde_at_n` and :func:`power_statement` from
``scorer/power_analysis.py``, both in the Paper Crane ``binder-scorer`` tree.
The three-zone verdict in :func:`three_zone_verdict` is ported from the
pre-registered policy in ``scorer/loto_eval.py``. Behaviour is unchanged; the
return type became a dataclass and the domain words changed from targets to
clusters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Hashable, Mapping, Sequence

import numpy as np
from scipy import stats

__all__ = [
    "BcaInterval",
    "paired_bca_ci",
    "macro_average_by_cluster",
    "micro_average",
    "cluster_means",
    "PREREGISTERED_MDE",
    "compute_mde_at_n",
    "power_statement",
    "three_zone_verdict",
    "THREE_ZONE_POLICY",
    "Zone",
]

_ALPHA = 0.05  # 95% CI
_Z_LO = stats.norm.ppf(_ALPHA / 2)
_Z_HI = stats.norm.ppf(1 - _ALPHA / 2)


# ---------------------------------------------------------------------------
# Macro vs micro averaging
# ---------------------------------------------------------------------------
def cluster_means(
    values: Sequence[float],
    cluster_ids: Sequence[Hashable],
) -> dict[Hashable, float]:
    """Mean value within each cluster, keyed by cluster id.

    This is the collapse step that makes the bootstrap honest: everything
    downstream resamples these per-cluster numbers, so one antigen contributes
    one observation however many complexes of it were deposited.

    NaN values are dropped within a cluster (an undefined recall should not
    poison its cluster); a cluster whose every value is NaN is omitted
    entirely, and the caller is expected to notice the missing key rather than
    receive a silent zero.
    """
    if len(values) != len(cluster_ids):
        raise ValueError(
            f"values and cluster_ids must be the same length, got "
            f"{len(values)} and {len(cluster_ids)}"
        )
    buckets: dict[Hashable, list[float]] = {}
    for value, cluster in zip(values, cluster_ids):
        if value != value:  # NaN check
            continue
        buckets.setdefault(cluster, []).append(float(value))
    return {
        cluster: sum(vals) / len(vals)
        for cluster, vals in buckets.items()
        if vals
    }


def macro_average_by_cluster(
    values: Sequence[float],
    cluster_ids: Sequence[Hashable],
) -> float:
    """Unweighted mean over clusters of the within-cluster mean.

    Invariant that matters: duplicating every row of one cluster does not
    change this number, while it does change :func:`micro_average`. That is
    exactly the bias the spec warns about — the benchmark's instance counts are
    an artefact of how often people crystallise a fashionable antigen.
    """
    per_cluster = cluster_means(values, cluster_ids)
    if not per_cluster:
        raise ValueError(
            "no finite values to macro-average; every row was NaN or the "
            "input was empty"
        )
    return sum(per_cluster.values()) / len(per_cluster)


def micro_average(values: Sequence[float]) -> float:
    """Plain per-instance mean.

    Opt-in only. Correct for "what fraction of deposited complexes does this
    happen to", wrong for "how well does this generalise across antigens".
    """
    finite = [float(v) for v in values if v == v]
    if not finite:
        raise ValueError(
            "no finite values to micro-average; every row was NaN or the "
            "input was empty"
        )
    return sum(finite) / len(finite)


# ---------------------------------------------------------------------------
# Paired BCa bootstrap
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BcaInterval:
    """A paired bootstrap interval on a mean delta.

    Attributes:
        point: observed mean of the per-cluster deltas.
        lo, hi: 95% BCa bounds (percentile bounds if the BCa adjustment
            degenerated — see :func:`paired_bca_ci`).
        n: number of clusters resampled. This is the real n; it is small.
        n_positive_deltas: clusters where the delta was strictly positive.
        sign_test_p: one-sided exact binomial p, H1: P(delta > 0) > 0.5.
        wilcoxon_p: one-sided Wilcoxon signed-rank p, or NaN below n = 10
            where the signed-rank null distribution is too coarse to trust.
        degenerate: True when the BCa correction could not be applied and the
            interval fell back to plain percentiles.
    """

    point: float
    lo: float
    hi: float
    n: int
    n_positive_deltas: int
    sign_test_p: float
    wilcoxon_p: float
    degenerate: bool = False

    @property
    def spans_zero(self) -> bool:
        """True when the interval contains zero, i.e. the result is inconclusive.

        NaN bounds (n = 0) count as spanning zero because the effect is
        unknown without observations.
        """
        if not (math.isfinite(self.lo) and math.isfinite(self.hi)):
            return True
        return self.lo <= 0.0 <= self.hi

    @property
    def width(self) -> float:
        """Interval width, NaN if either bound is undefined."""
        return self.hi - self.lo

    def to_dict(self) -> dict[str, object]:
        return {
            "point": self.point,
            "lo": self.lo,
            "hi": self.hi,
            "n": self.n,
            "n_positive_deltas": self.n_positive_deltas,
            "sign_test_p": self.sign_test_p,
            "wilcoxon_p": self.wilcoxon_p,
            "degenerate": self.degenerate,
            "spans_zero": self.spans_zero,
        }


def _percentile_ci(boot_means: np.ndarray) -> tuple[float, float]:
    lo = float(np.percentile(boot_means, 100 * (_ALPHA / 2)))
    hi = float(np.percentile(boot_means, 100 * (1 - _ALPHA / 2)))
    return lo, hi


def _bca_ci(
    deltas: np.ndarray, boot_means: np.ndarray, point: float
) -> tuple[float, float, bool]:
    """BCa bounds, or percentile bounds plus a degenerate flag.

    Returns ``(lo, hi, degenerate)``. Every early return is a case where the
    BCa correction is undefined rather than merely extreme, and silently
    reporting a percentile interval as BCa would misstate the method.

    Ported from ``scorer/bootstrap_ci.py`` (binder-scorer).
    """
    n = len(deltas)

    prop_below = float(np.mean(boot_means < point))
    if prop_below <= 0.0 or prop_below >= 1.0:
        lo, hi = _percentile_ci(boot_means)
        return lo, hi, True
    z0 = stats.norm.ppf(prop_below)

    # Acceleration from the jackknife skewness of the cluster deltas.
    jack = np.array([np.mean(np.delete(deltas, i)) for i in range(n)])
    diffs = jack.mean() - jack
    denom = 6.0 * (float(np.sum(diffs**2)) ** 1.5)
    if denom == 0.0:
        lo, hi = _percentile_ci(boot_means)
        return lo, hi, True
    a = float(np.sum(diffs**3) / denom)

    if not (math.isfinite(z0) and math.isfinite(a)):
        lo, hi = _percentile_ci(boot_means)
        return lo, hi, True

    def _adjusted_quantile(z: float) -> float | None:
        denom2 = 1 - a * (z0 + z)
        if denom2 == 0:
            return None
        return float(stats.norm.cdf(z0 + (z0 + z) / denom2))

    p_lo = _adjusted_quantile(_Z_LO)
    p_hi = _adjusted_quantile(_Z_HI)
    if p_lo is None or p_hi is None:
        lo, hi = _percentile_ci(boot_means)
        return lo, hi, True

    lo = float(np.percentile(boot_means, 100 * p_lo))
    hi = float(np.percentile(boot_means, 100 * p_hi))
    return lo, hi, False


def paired_bca_ci(
    per_cluster_deltas: Sequence[float],
    n_boot: int = 10000,
    seed: int = 0,
) -> BcaInterval:
    """Cluster-clustered paired BCa bootstrap of the mean delta.

    Each element is one antigen cluster's (arm_b - arm_a) delta on the primary
    endpoint, already collapsed by :func:`cluster_means`. Resampling those
    cluster deltas propagates the small cluster-level uncertainty instead of
    the much larger and fictitious instance-level n.

    Interval method: BCa (bias-corrected and accelerated) percentile
    bootstrap, falling back to the plain percentile interval when the BCa
    adjustment degenerates — see :func:`_bca_ci`. Also returned: a one-sided
    exact sign test, and a one-sided Wilcoxon signed-rank p when n >= 10.

    Deterministic given ``seed``.

    Ported from ``scorer/bootstrap_ci.py`` (binder-scorer).
    """
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")

    deltas = np.asarray([float(d) for d in per_cluster_deltas], dtype=float)
    if deltas.size and not np.all(np.isfinite(deltas)):
        raise ValueError(
            "per_cluster_deltas contains NaN or inf; drop the offending "
            "cluster upstream so the drop can be logged with its reason"
        )

    n = int(deltas.size)
    point = float(np.mean(deltas)) if n else float("nan")
    n_pos = int(np.sum(deltas > 0))

    if n == 0:
        return BcaInterval(
            point=float("nan"),
            lo=float("nan"),
            hi=float("nan"),
            n=0,
            n_positive_deltas=0,
            sign_test_p=float("nan"),
            wilcoxon_p=float("nan"),
            degenerate=True,
        )

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = deltas[idx].mean(axis=1)

    if np.all(boot_means == boot_means[0]):
        lo = hi = float(boot_means[0])
        degenerate = True
    else:
        lo, hi, degenerate = _bca_ci(deltas, boot_means, point)

    # One-sided sign test, ties excluded from the denominator.
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
            # All-zero or otherwise degenerate input: no signed-rank statistic.
            wilcoxon_p = float("nan")
    else:
        wilcoxon_p = float("nan")

    return BcaInterval(
        point=point,
        lo=lo,
        hi=hi,
        n=n,
        n_positive_deltas=n_pos,
        sign_test_p=sign_p,
        wilcoxon_p=wilcoxon_p,
        degenerate=degenerate,
    )


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------
# Pre-registered MDE at n = 11 clusters, alpha = 0.05, power = 0.80, kept at
# the binder-scorer value so the two harnesses state the same floor. A delta
# below this is "untested" (insufficient power), NOT "disproven".
PREREGISTERED_MDE: float = 0.035

_NORMAL_PPF_80 = 0.8416  # stats.norm.ppf(0.80)
_NORMAL_PPF_975 = 1.9600  # stats.norm.ppf(0.975)


def compute_mde_at_n(
    n: int,
    alpha: float = 0.05,
    power: float = 0.80,
    sigma_assumed: float = 0.0414,
) -> float:
    """Conservative minimum detectable effect at ``n`` clusters.

    Normal approximation to a one-sided paired t test. ``sigma_assumed`` is
    calibrated so that at n = 11 the MDE equals :data:`PREREGISTERED_MDE`;
    the empirical standard deviation of per-fold precision deltas on
    comparable data is about 0.04.

    Returns ``inf`` below n = 2, where no effect is detectable at all.

    Ported from ``scorer/power_analysis.py`` (binder-scorer).
    """
    if n < 2:
        return float("inf")
    return float((_NORMAL_PPF_975 + _NORMAL_PPF_80) * sigma_assumed / math.sqrt(n))


def power_statement(observed_delta: float, n_clusters: int) -> str:
    """Human-readable power assessment, phrased so a null cannot be oversold.

    A delta below the MDE is UNTESTED: the available sample cannot resolve
    an effect of that size.

    Ported from ``scorer/power_analysis.py`` (binder-scorer).
    """
    mde = compute_mde_at_n(n_clusters)
    if not math.isfinite(observed_delta):
        return (
            f"No delta could be computed at n={n_clusters} clusters "
            f"(pre-registered MDE={mde:.3f}). This result is UNTESTED."
        )
    if abs(observed_delta) < mde:
        return (
            f"Delta={observed_delta:.3f} is below the pre-registered "
            f"MDE={mde:.3f} at n={n_clusters} clusters. This result is "
            f"UNTESTED (underpowered); the benchmark is insufficiently "
            f"powered to draw a conclusion. More antigen clusters are "
            f"required before concluding anything."
        )
    return (
        f"Delta={observed_delta:.3f} exceeds the pre-registered MDE="
        f"{mde:.3f} at n={n_clusters} clusters. Effect is detectable / "
        f"adequately powered."
    )


# ---------------------------------------------------------------------------
# Pre-registered verdict
# ---------------------------------------------------------------------------
class Zone(str, Enum):
    """The three pre-registered outcomes. ``str`` subclass so it JSON-encodes."""

    FILTER_HELPS = "FILTER_HELPS"
    FILTER_HURTS = "FILTER_HURTS"
    INCONCLUSIVE = "INCONCLUSIVE"


THREE_ZONE_POLICY = (
    "PRE-REGISTERED THREE-ZONE POLICY. Written before the numbers were seen, "
    "so the verdict cannot be chosen after the fact.\n"
    "Primary endpoint = delta in top-k patch recall from adding the reality "
    "filter to the strongest predictor arm, macro-averaged per antigen "
    "cluster. The aggregate interval is a cluster-clustered BCa bootstrap "
    "over clusters, never over instances.\n"
    "Zones, decided on the interval whenever one could be computed:\n"
    "  FILTER_HELPS : CI lower bound > 0.\n"
    "  FILTER_HURTS : CI upper bound < 0.\n"
    "  INCONCLUSIVE : the CI spans zero. An inconclusive result is reported "
    "as inconclusive, not as a point estimate.\n"
    "Only when no interval exists (n = 0, or non-finite bounds) does the "
    "fallback apply: HELPS if per-cluster wins >= n - 1, HURTS if wins <= "
    "(n // 2 - 1), else INCONCLUSIVE.\n"
    "The false-rejection rate on known-real epitopes is reported alongside "
    "and is never traded off against the primary endpoint: a filter that "
    "raises patch recall while killing real epitopes has failed."
)


def three_zone_verdict(
    interval: BcaInterval | Mapping[str, float],
    n_clusters: int | None = None,
) -> Zone:
    """Apply the pre-registered three-zone rule to an aggregate interval.

    Args:
        interval: a :class:`BcaInterval`, or a mapping carrying ``lo``, ``hi``
            and ``n_positive_deltas``.
        n_clusters: number of clusters; taken from the interval when omitted.

    Ported from ``_three_zone_verdict`` in ``scorer/loto_eval.py``
    (binder-scorer), with the domain words changed from targets to clusters
    and **one deliberate correction**: in the original, the win-count clauses
    sat as ``or`` alternatives beside the CI clauses, so an exactly-null
    result (every delta 0.0, lo = hi = 0, wins = 0) fell through
    ``wins <= n // 2 - 1`` and was declared a loss. Here a finite interval is
    authoritative — if it spans zero the verdict is INCONCLUSIVE, which is
    what the pre-registered policy text actually says — and the win-count
    heuristic is only consulted when the interval could not be computed.
    """
    if isinstance(interval, BcaInterval):
        lo, hi = interval.lo, interval.hi
        wins = interval.n_positive_deltas
        n = interval.n if n_clusters is None else n_clusters
    else:
        lo = float(interval.get("lo", float("nan")))
        hi = float(interval.get("hi", float("nan")))
        wins = int(interval.get("n_positive_deltas", 0))
        n = int(interval.get("n", 0)) if n_clusters is None else n_clusters

    if n == 0:
        return Zone.INCONCLUSIVE

    # Epsilon tolerance: subnormal bootstrap dust (lo = 5.5e-18 when most
    # deltas are exactly zero) must not flip a verdict on a floating-point
    # knife-edge.
    eps = 1e-9
    if math.isfinite(lo) and math.isfinite(hi):
        if lo > eps:
            return Zone.FILTER_HELPS
        if hi < -eps:
            return Zone.FILTER_HURTS
        return Zone.INCONCLUSIVE

    if wins >= n - 1:
        return Zone.FILTER_HELPS
    if wins <= (n // 2 - 1):
        return Zone.FILTER_HURTS
    return Zone.INCONCLUSIVE
