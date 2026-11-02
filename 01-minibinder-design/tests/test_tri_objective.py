"""Check seed aggregation, confidence gates, and ranking across the three scoring models."""
import math, sys
from pathlib import Path

import pytest

from minibinder.design.tri_objective import (
    Thresholds, score_design, seed_spread, aggregate_protenix_seeds,
    rank_designs, calibrate, LEGACY_IPSAE_GATE,
)

# The one design that bound, with its real measured metrics.
L79 = dict(protenix_iptm=0.9490, protenix_spread=0.0006, esmfold_iptm=0.8004,
           esmfold_binder_plddt=0.85, boltz2_iptm=0.90, ipsae_min=0.8279)


class TestSeedSpread:
    def test_identical_seeds_give_zero(self):
        assert seed_spread([0.9, 0.9, 0.9]) == 0.0

    def test_single_seed_is_nan_not_zero(self):
        """A lone seed has no spread; scoring it 0.0 would be a free pass."""
        assert math.isnan(seed_spread([0.9]))

    def test_empty_is_nan(self):
        assert math.isnan(seed_spread([]))

    def test_spread_increases_with_disagreement(self):
        assert seed_spread([0.9, 0.5]) > seed_spread([0.9, 0.89])

    def test_nan_entries_ignored(self):
        assert seed_spread([0.9, float("nan"), 0.9]) == 0.0

    def test_aggregate_reports_mean_min_and_n(self):
        a = aggregate_protenix_seeds([0.90, 0.94, 0.92])
        assert a["n_seeds"] == 3
        assert a["protenix_iptm_min"] == 0.90
        assert abs(a["protenix_iptm"] - 0.92) < 1e-9


class TestGates:
    def test_real_binder_passes(self):
        """Non-negotiable: gates derived from l79 must admit l79."""
        s = score_design("l79", **L79)
        assert s.passes, f"gates rejected the real binder: {s.gates_failed}"

    def test_high_seed_spread_fails(self):
        assert not score_design("x", **{**L79, "protenix_spread": 0.5}).passes

    def test_low_protenix_fails(self):
        assert not score_design("x", **{**L79, "protenix_iptm": 0.50}).passes

    def test_low_esmfold_fails(self):
        assert not score_design("x", **{**L79, "esmfold_iptm": 0.10}).passes

    def test_missing_metric_is_a_failure_not_a_pass(self):
        s = score_design("x", protenix_iptm=0.95)
        assert not s.passes
        assert any("missing" in g for g in s.gates_failed)

    def test_ipsae_is_not_gated_by_default(self):
        """ipSAE ranked the real binder 10/20; it must not gate."""
        assert LEGACY_IPSAE_GATE is False
        s = score_design("x", **{**L79, "ipsae_min": 0.01})
        assert s.passes


class TestAxes:
    def test_axes_are_independent(self):
        b = score_design("b", protenix_iptm=0.98, protenix_spread=0.0001,
                         boltz2_iptm=0.95, esmfold_iptm=0.52,
                         esmfold_binder_plddt=0.52)
        e = score_design("e", protenix_iptm=0.72, protenix_spread=0.09,
                         boltz2_iptm=0.62, esmfold_iptm=0.89,
                         esmfold_binder_plddt=0.94)
        assert b.bind > e.bind
        assert e.express > b.express

    def test_bind_survives_missing_expression(self):
        s = score_design("x", protenix_iptm=0.95, protenix_spread=0.001,
                         boltz2_iptm=0.9)
        assert not math.isnan(s.bind) and math.isnan(s.express)

    def test_express_survives_missing_binding(self):
        s = score_design("x", esmfold_iptm=0.85, esmfold_binder_plddt=0.9)
        assert not math.isnan(s.express) and math.isnan(s.bind)

    def test_all_missing_gives_nan_composite(self):
        assert math.isnan(score_design("x").composite)

    def test_spread_is_lower_is_better(self):
        lo = score_design("lo", **{**L79, "protenix_spread": 0.0001})
        hi = score_design("hi", **{**L79, "protenix_spread": 0.05})
        assert lo.bind > hi.bind

    def test_scores_are_bounded(self):
        s = score_design("x", protenix_iptm=99.0, protenix_spread=-5.0,
                         boltz2_iptm=99.0, esmfold_iptm=99.0,
                         esmfold_binder_plddt=99.0)
        assert 0.0 <= s.composite <= 1.0


class TestRanking:
    def test_binder_outranks_mediocre(self):
        ds = [score_design("mid", protenix_iptm=0.80, protenix_spread=0.05,
                           boltz2_iptm=0.75, esmfold_iptm=0.60,
                           esmfold_binder_plddt=0.70),
              score_design("l79", **L79)]
        assert rank_designs(ds)[0].name == "l79"

    def test_passing_always_outranks_failing(self):
        strong_fail = score_design("f", protenix_iptm=0.99, protenix_spread=0.99,
                                   boltz2_iptm=0.99, esmfold_iptm=0.99,
                                   esmfold_binder_plddt=0.99)
        weak_pass = score_design("p", **L79)
        assert rank_designs([strong_fail, weak_pass])[0].name == "p"


class TestCalibration:
    def test_recalibrates_from_positives(self):
        th = calibrate([{**L79, "bound": 1}, {**L79, "protenix_iptm": 0.80, "bound": 0}])
        assert th.protenix_iptm_min == pytest.approx(0.949, abs=1e-3)
        assert "CALIBRATED" in th.calib["protenix_iptm_min"]

    def test_raises_without_positives(self):
        with pytest.raises(ValueError):
            calibrate([{**L79, "bound": 0}])

    def test_recalibrated_gates_still_admit_the_binder(self):
        th = calibrate([{**L79, "bound": 1}])
        assert score_design("l79", **L79, thresholds=th).passes

    def test_default_thresholds_record_provenance(self):
        th = Thresholds()
        assert "CALIBRATED" in th.calib["protenix_iptm_min"]
        assert "UNCALIBRATED" in th.calib["boltz2_iptm_min"]
