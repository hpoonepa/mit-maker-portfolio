from __future__ import annotations

import math
import statistics

from scorer.power_analysis import (
    DESIRED_MDE,
    PREREGISTERED_MDE,
    mde_from_deltas,
    mde_from_sigma,
    power_statement,
    targets_needed_for_mde,
)

# The real v1 per-target ΔP@k vs B0 from the 2026-06-28 benchmark (mean = -0.058).
# Their sample SD (~0.178) is what the *achieved* MDE must be derived from.
V1_DELTAS = [-0.10, -0.20, -0.05, 0.10, 0.33, 0.0, 0.0, -0.17, 0.0, -0.30, -0.25]


def test_desired_mde_is_aspirational_not_a_calibrated_constant():
    # 0.035 is the sensitivity we WANT, not what n=11 folds achieve.
    assert DESIRED_MDE == 0.035
    assert PREREGISTERED_MDE == DESIRED_MDE  # back-compat alias, same meaning


def test_achieved_mde_uses_real_delta_spread_not_circular_sigma():
    # Empirical SD of the paired deltas ~0.178 -> achieved MDE ~0.15, NOT 0.035.
    sigma = statistics.stdev(V1_DELTAS)
    assert 0.16 < sigma < 0.19
    mde = mde_from_deltas(V1_DELTAS)
    assert 0.13 < mde < 0.17
    # The old reverse-engineered sigma=0.0414 understated the MDE ~4x.
    assert mde > 3 * DESIRED_MDE


def test_mde_from_sigma_matches_closed_form():
    z = 1.9600 + 0.8416
    expected = z * 0.178 / math.sqrt(11)
    assert math.isclose(mde_from_sigma(11, 0.178), expected, rel_tol=1e-6)


def test_mde_undefined_for_tiny_n():
    assert mde_from_sigma(1, 0.1) == float("inf")
    assert mde_from_deltas([0.05]) == float("inf")


def test_v2_tie_is_untested_under_corrected_mde():
    # v2's -0.014 vs B0 is far below the ~0.15 achieved MDE -> UNTESTED, not "tie".
    stmt = power_statement(observed_delta=-0.014, deltas=V1_DELTAS)
    assert "untested" in stmt.lower() or "underpowered" in stmt.lower()
    assert "MDE" in stmt
    assert "disproven" not in stmt.lower()


def test_v1_loss_is_also_untested_not_a_powered_loss():
    # -0.058 was reported as a "powered loss"; under the real MDE it is untested.
    stmt = power_statement(observed_delta=-0.058, deltas=V1_DELTAS)
    assert "untested" in stmt.lower() or "underpowered" in stmt.lower()


def test_large_delta_is_detectable():
    stmt = power_statement(observed_delta=0.30, deltas=V1_DELTAS)
    assert "powered" in stmt.lower()
    assert "untested" not in stmt.lower()


def test_targets_needed_to_reach_desired_mde():
    sigma = statistics.stdev(V1_DELTAS)
    need = targets_needed_for_mde(DESIRED_MDE, sigma)
    # ~200 targets to detect 0.035 at this variance — the case for scaling up.
    assert 150 < need < 260
