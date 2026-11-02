from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


# Desired Precision@k sensitivity. Achieved MDE is computed separately from
# the empirical spread of paired per-target deltas (``mde_from_deltas``).
DESIRED_MDE: float = 0.035

# Back-compat alias for older imports; same meaning (the desired sensitivity).
PREREGISTERED_MDE: float = DESIRED_MDE

_NORMAL_PPF_80 = 0.8416   # scipy.stats.norm.ppf(0.80)
_NORMAL_PPF_975 = 1.9600  # scipy.stats.norm.ppf(0.975)


def mde_from_sigma(
    n: int, sigma: float, alpha: float = 0.05, power: float = 0.80
) -> float:
    """Achieved MDE for a one-sided paired test at ``n`` targets.

    ``MDE = (z_alpha + z_beta) * sigma / sqrt(n)`` where ``sigma`` is the sample
    SD of the PAIRED per-target deltas (candidate - baseline). This is the true
    detectable effect given the data's own variance — no calibrated constant.
    (alpha/power are fixed to the standard 0.05 / 0.80 z-values.)
    """
    if n < 2 or sigma != sigma:  # too few folds, or nan sigma
        return float("inf")
    return float((_NORMAL_PPF_975 + _NORMAL_PPF_80) * sigma / math.sqrt(n))


def mde_from_deltas(
    deltas: Sequence[float], alpha: float = 0.05, power: float = 0.80
) -> float:
    """Achieved MDE computed from the actual per-target paired deltas.

    Derives sigma as the sample SD of ``deltas`` — the correct quantity for the
    paired-difference MDE formula. Replaces the reverse-engineered sigma=0.0414
    that made the n=11 MDE circularly equal 0.035.
    """
    n = len(deltas)
    if n < 2:
        return float("inf")
    return mde_from_sigma(n, statistics.stdev(deltas), alpha=alpha, power=power)


def targets_needed_for_mde(
    target_mde: float, sigma: float, alpha: float = 0.05, power: float = 0.80
) -> int:
    """Number of paired folds needed to detect ``target_mde`` given ``sigma``."""
    if target_mde <= 0 or sigma != sigma:
        return 0
    z = _NORMAL_PPF_975 + _NORMAL_PPF_80
    return math.ceil((z * sigma / target_mde) ** 2)


def power_statement(observed_delta: float, deltas: Sequence[float]) -> str:
    """Power assessment using the MDE derived from the deltas' own spread.

    ``deltas`` is the list of per-target paired deltas this run produced; their
    sample SD sets the achieved MDE. Pass the same list whose mean is
    ``observed_delta``. A delta below the achieved MDE is UNTESTED (insufficient
    power), NOT disproven.
    """
    n = len(deltas)
    if n < 2:
        return (
            f"Only n={n} target fold(s) — power is undefined; "
            f"acquire more targets before drawing any conclusion."
        )
    sigma = statistics.stdev(deltas)
    mde = mde_from_deltas(deltas)
    if abs(observed_delta) < mde:
        need = targets_needed_for_mde(DESIRED_MDE, sigma)
        return (
            f"Delta={observed_delta:+.3f} is below the ACHIEVED MDE={mde:.3f} "
            f"(empirical delta SD={sigma:.3f} at n={n}). This result is UNTESTED "
            f"(underpowered): the study cannot yet resolve it — unresolved, not ruled out. "
            f"Detecting the desired MDE={DESIRED_MDE:.3f} at this variance would "
            f"need ~{need} targets."
        )
    return (
        f"Delta={observed_delta:+.3f} exceeds the ACHIEVED MDE={mde:.3f} "
        f"(empirical delta SD={sigma:.3f} at n={n}). Effect is adequately powered."
    )
