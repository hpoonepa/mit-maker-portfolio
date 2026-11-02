"""Tests for scripts/consensus_rank.py — the VP3-derived consensus scorer."""
import csv, importlib.util, math, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cr", ROOT / "scripts" / "consensus_rank.py")
cr = importlib.util.module_from_spec(spec)
sys.modules["cr"] = cr
spec.loader.exec_module(cr)

# The design that actually bound: KD 546/666 nM, ranks 1/17, 1/17, 2/17.
L79 = dict(name="l79_s469532_mpnn9", protenix_iptm=0.949,
           protenix_seed_spread=0.0006, esmfold_iptm=0.8004)


def write_csv(tmp_path, rows, cols=None):
    cols = cols or ["name", "protenix_iptm", "protenix_seed_spread",
                    "esmfold_iptm", "solublempnn_delta"]
    p = tmp_path / "d.csv"
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(p)


class TestPercentile:
    def test_higher_is_better(self):
        assert cr.percentile_rank([1, 2, 3], False) == [0.0, 0.5, 1.0]

    def test_lower_is_better_inverts(self):
        assert cr.percentile_rank([1, 2, 3], True) == [1.0, 0.5, 0.0]

    def test_ties_share_midpoint(self):
        out = cr.percentile_rank([5, 5, 9], False)
        assert out[0] == out[1] and out[2] == 1.0

    def test_none_passthrough(self):
        assert cr.percentile_rank([1, None, 3], False)[1] is None

    def test_single_value(self):
        assert cr.percentile_rank([7], False) == [0.5]

    def test_all_none(self):
        assert cr.percentile_rank([None, None], False) == [None, None]


class TestGates:
    def test_binder_is_never_excluded(self, tmp_path):
        """Non-negotiable: gates derived from l79 must admit l79."""
        d = cr.score(cr.read_designs(write_csv(tmp_path, [L79])))[0]
        assert d.passes, f"gates rejected the one real binder: {d.gates_failed}"

    def test_high_seed_spread_fails(self, tmp_path):
        r = dict(L79, name="spread", protenix_seed_spread=0.5)
        assert not cr.score(cr.read_designs(write_csv(tmp_path, [r])))[0].passes

    def test_low_protenix_fails(self, tmp_path):
        r = dict(L79, name="lowp", protenix_iptm=0.4)
        assert not cr.score(cr.read_designs(write_csv(tmp_path, [r])))[0].passes

    def test_missing_metric_reported(self, tmp_path):
        r = {"name": "bare", "protenix_iptm": 0.95}
        d = cr.score(cr.read_designs(write_csv(tmp_path, [r])))[0]
        assert any("missing" in g for g in d.gates_failed)


class TestRanking:
    def test_binder_profile_ranks_first(self, tmp_path):
        rows = [L79,
                dict(name="weak", protenix_iptm=0.60, protenix_seed_spread=0.40,
                     esmfold_iptm=0.40),
                dict(name="mid", protenix_iptm=0.85, protenix_seed_spread=0.05,
                     esmfold_iptm=0.70)]
        assert cr.score(cr.read_designs(write_csv(tmp_path, rows)))[0].name == L79["name"]

    def test_axes_are_independent(self, tmp_path):
        rows = [dict(name="binder_only", protenix_iptm=0.99, protenix_seed_spread=0.0001,
                     esmfold_iptm=0.20, solublempnn_delta=-0.5),
                dict(name="expr_only", protenix_iptm=0.50, protenix_seed_spread=0.40,
                     esmfold_iptm=0.95, solublempnn_delta=0.5)]
        ds = {d.name: d for d in cr.score(cr.read_designs(write_csv(tmp_path, rows)))}
        assert ds["binder_only"].bind > ds["expr_only"].bind
        assert ds["expr_only"].express > ds["binder_only"].express

    def test_bind_score_survives_missing_expression(self, tmp_path):
        r = {"name": "b", "protenix_iptm": 0.95, "protenix_seed_spread": 0.001}
        d = cr.score(cr.read_designs(write_csv(tmp_path, [r])))[0]
        assert not math.isnan(d.bind) and math.isnan(d.express)


class TestIO:
    def test_column_aliases(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("candidate_id,protenix_ipTM,seed_spread,esmfold2_ipTM\nx,0.95,0.001,0.8\n")
        d = cr.read_designs(str(p))[0]
        assert d.name == "x" and d.raw["esmfold_iptm"] == 0.8
        assert d.raw["protenix_seed_spread"] == 0.001

    def test_missing_name_column_is_fatal(self, tmp_path):
        p = tmp_path / "b.csv"
        p.write_text("foo,bar\n1,2\n")
        with pytest.raises(SystemExit):
            cr.read_designs(str(p))

    @pytest.mark.parametrize("blank", ["", "NA", "nan", "None", "-"])
    def test_blank_markers_become_none(self, blank):
        assert cr._num(blank) is None

    def test_roundtrip_write(self, tmp_path):
        ds = cr.score(cr.read_designs(write_csv(tmp_path, [L79])))
        out = tmp_path / "o.csv"
        cr.write(ds, str(out))
        rows = list(csv.DictReader(open(out)))
        assert rows[0]["name"] == L79["name"] and rows[0]["passes_gates"] == "PASS"


class TestSequenceFlags:
    def test_cysteine_flagged(self):
        assert any("Cys" in f for f in cr.sequence_flags("MACDEFGHIKC"))

    def test_clean_helical_sequence_is_quiet(self):
        assert cr.sequence_flags("MKKLRELTPLQKKLLKDPKVREWLRITYRVITDDEPPSEEESELQ") == []

    def test_empty_sequence(self):
        assert cr.sequence_flags("") == []


def test_builtin_selftest_passes():
    assert cr.selftest() == 0
