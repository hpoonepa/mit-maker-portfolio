#!/usr/bin/env python3
"""Rank saved binder designs using the retrospective VP3 assay analysis.

WHAT THE EVIDENCE ACTUALLY SAYS  (derived 2026-09-21 from the Adaptyv BLI
packages joined to 5G51_FINAL_20_DOCUMENTED.csv; see METHODS at the bottom)

  Binding axis  (n = 1 positive - treat as a hypothesis, not a law)
    l79_s469532_mpnn9 ranked  1/17 on protenix_ipTM          (0.9490)
    l79_s469532_mpnn9 ranked  1/17 on LOW protenix seed spread (0.0006)
    l79_s469532_mpnn9 ranked  2/17 on esmfold2_ipTM          (0.8004)
    l79_s469532_mpnn9 ranked 10/20 on ipSAE_min  <- ipSAE FAILED on ground truth

  Expression axis  (n = 17-18 with outcomes; NOTHING reaches p < 0.05)
    esmfold2_ipTM         AUC 0.653  p 0.32
    solublempnn delta     AUC 0.725  p 0.12   (soluble minus vanilla)
    solublempnn raw       AUC 0.463  p 0.83   <- the raw score is noise
    protenix_ipTM         AUC 0.500  p 1.00   <- zero expression signal

  These two axes are retrospective hypotheses for this panel. One positive
  and nonsignificant expression comparisons do not establish general binding
  or expression predictors.

USAGE
    python consensus_rank.py designs.csv -o ranked.csv
    python consensus_rank.py designs.csv --calibrate labelled.csv
    python consensus_rank.py --selftest

INPUT COLUMNS (case-insensitive; missing optional columns are tolerated)
    name                   required
    protenix_iptm          0-1, higher better
    protenix_seed_spread   >=0, LOWER better
    esmfold_iptm           0-1, higher better      (alias: esmfold2_iptm)
    solublempnn_delta      optional, higher better (soluble minus vanilla)
    sequence               optional, enables composition flags"""
from __future__ import annotations
import argparse, csv, json, math, sys
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------
# Gates. Set just below the one design that bound so it is never excluded.
# These are ONE observation. Re-derive with --calibrate as soon as you have
# more ground truth; do not treat them as validated thresholds.
# ----------------------------------------------------------------------------
GATES = {
    "protenix_iptm":        (">=", 0.93,  "binder scored 0.9490 (rank 1/17)"),
    "protenix_seed_spread": ("<=", 0.010, "binder scored 0.0006 (lowest of 17)"),
    "esmfold_iptm":         (">=", 0.75,  "binder scored 0.8004 (rank 2/17)"),
}

# Axis weights. Within an axis, weights sum to 1.
W_BIND = {"protenix_iptm": 0.60, "protenix_seed_spread": 0.40}
W_EXPR = {"esmfold_iptm": 0.55, "solublempnn_delta": 0.45}
# Between axes. Expression is weighted heavily because 16/35 designs across
# both campaigns never produced a single measurable curve - a design that
# does not express cannot bind no matter how good its interface score is.
W_AXIS = {"bind": 0.55, "express": 0.45}

# True when a LOWER raw value is better.
LOWER_IS_BETTER = {"protenix_seed_spread"}

ALIASES = {
    "esmfold2_iptm": "esmfold_iptm", "esmfold_ptm": "esmfold_iptm",
    "protenix_iptm_mean": "protenix_iptm", "seed_spread": "protenix_seed_spread",
    "protenix_spread": "protenix_seed_spread", "candidate_id": "name",
    "design": "name", "id": "name", "sol_delta": "solublempnn_delta",
    "delta_mono": "solublempnn_delta", "delta_monomer": "solublempnn_delta",
}
METRICS = ["protenix_iptm", "protenix_seed_spread", "esmfold_iptm", "solublempnn_delta"]


@dataclass
class Design:
    name: str
    raw: dict = field(default_factory=dict)
    pct: dict = field(default_factory=dict)
    bind: float = float("nan")
    express: float = float("nan")
    composite: float = float("nan")
    gates_failed: list = field(default_factory=list)
    flags: list = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return not self.gates_failed


def _norm_key(k: str) -> str:
    k = k.strip().lower().replace(" ", "_").replace("-", "_").replace("'", "")
    return ALIASES.get(k, k)


def _num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() in ("NA", "NAN", "NONE", "NULL", "-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return None if math.isnan(f) else f


def read_designs(path: str) -> list[Design]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        if rdr.fieldnames is None:
            raise SystemExit(f"FATAL: {path} has no header row.")
        keymap = {f: _norm_key(f) for f in rdr.fieldnames}
        if "name" not in keymap.values():
            raise SystemExit(
                f"FATAL: no 'name' column in {path}. Columns seen: {rdr.fieldnames}")
        out = []
        for row in rdr:
            d = {keymap[k]: v for k, v in row.items() if k in keymap}
            name = (d.get("name") or "").strip()
            if not name:
                continue
            des = Design(name=name)
            for m in METRICS:
                des.raw[m] = _num(d.get(m))
            des.raw["sequence"] = (d.get("sequence") or "").strip().upper()
            out.append(des)
    if not out:
        raise SystemExit(f"FATAL: no data rows in {path}.")
    return out


def percentile_rank(values: list, lower_better: bool) -> list:
    """Fractional percentile in [0,1]; ties share the midpoint. None -> None."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if not idx:
        return out
    if len(idx) == 1:
        out[idx[0]] = 0.5
        return out
    vals = [values[i] for i in idx]
    order = sorted(range(len(idx)), key=lambda j: vals[j], reverse=lower_better)
    # average ranks across ties so equal inputs get equal scores
    ranks = [0.0] * len(idx)
    j = 0
    while j < len(order):
        k = j
        while k + 1 < len(order) and vals[order[k + 1]] == vals[order[j]]:
            k += 1
        mid = (j + k) / 2.0
        for t in range(j, k + 1):
            ranks[order[t]] = mid
        j = k + 1
    denom = len(idx) - 1
    for pos, i in enumerate(idx):
        out[i] = ranks[pos] / denom
    return out


def _axis(des: Design, weights: dict) -> float:
    num = den = 0.0
    for m, w in weights.items():
        p = des.pct.get(m)
        if p is not None:
            num += w * p
            den += w
    return num / den if den > 0 else float("nan")


def sequence_flags(seq: str) -> list:
    f = []
    if not seq:
        return f
    n = len(seq)
    if "C" in seq:
        f.append(f"{seq.count('C')}xCys")
    hyd = sum(seq.count(a) for a in "AVILMFWYC")
    if 100 * hyd / n > 48:
        f.append(f"hydrophobic {100*hyd/n:.0f}%")
    run = best = 0
    for a in seq:
        run = run + 1 if a in "AVILMFWYC" else 0
        best = max(best, run)
    if best >= 7:
        f.append(f"hydrophobic run {best}")
    net = sum(seq.count(a) for a in "KR") - sum(seq.count(a) for a in "DE")
    if abs(net) >= 12:
        f.append(f"net charge {net:+d}")
    return f


def score(designs: list[Design]) -> list[Design]:
    for m in METRICS:
        col = [d.raw.get(m) for d in designs]
        pcts = percentile_rank(col, lower_better=(m in LOWER_IS_BETTER))
        for d, p in zip(designs, pcts):
            d.pct[m] = p
    for d in designs:
        d.bind = _axis(d, W_BIND)
        d.express = _axis(d, W_EXPR)
        parts, wts = [], []
        if not math.isnan(d.bind):
            parts.append(W_AXIS["bind"] * d.bind); wts.append(W_AXIS["bind"])
        if not math.isnan(d.express):
            parts.append(W_AXIS["express"] * d.express); wts.append(W_AXIS["express"])
        d.composite = sum(parts) / sum(wts) if wts else float("nan")
        d.gates_failed = []
        for m, (op, thr, _why) in GATES.items():
            v = d.raw.get(m)
            if v is None:
                d.gates_failed.append(f"{m}:missing")
            elif op == ">=" and v < thr:
                d.gates_failed.append(f"{m}={v:g}<{thr:g}")
            elif op == "<=" and v > thr:
                d.gates_failed.append(f"{m}={v:g}>{thr:g}")
        d.flags = sequence_flags(d.raw.get("sequence", ""))
    designs.sort(key=lambda x: (-(x.composite if not math.isnan(x.composite) else -1)))
    return designs


def calibrate(path: str) -> dict:
    """Recompute gates from labelled ground truth.

    Needs columns: the metric columns plus `bound` (1/0) and/or `expressed` (1/0).
    Gate = the minimum (or maximum) value observed among designs that bound,
    which is the only defensible threshold from a positives-only calibration.
    """
    ds = read_designs(path)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    keymap = {f: _norm_key(f) for f in rows[0].keys()}
    lab = []
    for r in rows:
        d = {keymap[k]: v for k, v in r.items()}
        lab.append(_num(d.get("bound")))
    pos = [d for d, y in zip(ds, lab) if y == 1]
    if not pos:
        raise SystemExit("FATAL: --calibrate file has no rows with bound=1.")
    new = {}
    for m, (op, _old, _why) in GATES.items():
        vals = [d.raw.get(m) for d in pos if d.raw.get(m) is not None]
        if not vals:
            continue
        thr = min(vals) if op == ">=" else max(vals)
        new[m] = (op, round(thr, 4), f"from {len(vals)} binder(s), n={len(ds)} panel")
    return new


def write(designs: list[Design], out: str):
    cols = (["rank", "name", "composite", "bind_score", "express_score", "passes_gates"]
            + METRICS + ["pct_" + m for m in METRICS] + ["gates_failed", "seq_flags"])
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i, d in enumerate(designs, 1):
            fmt = lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.4f}"
            w.writerow([i, d.name, fmt(d.composite), fmt(d.bind), fmt(d.express),
                        "PASS" if d.passes else "fail"]
                       + [fmt(d.raw.get(m)) for m in METRICS]
                       + [fmt(d.pct.get(m)) for m in METRICS]
                       + ["; ".join(d.gates_failed), "; ".join(d.flags)])


def report(designs: list[Design], top: int):
    n = len(designs)
    npass = sum(1 for d in designs if d.passes)
    print(f"\n{'='*84}\nCONSENSUS RANKING - {n} designs, {npass} pass all gates\n{'='*84}")
    cov = {m: sum(1 for d in designs if d.raw.get(m) is not None) for m in METRICS}
    print("metric coverage: " + "  ".join(f"{m}={cov[m]}/{n}" for m in METRICS))
    missing = [m for m in METRICS if cov[m] == 0]
    if missing:
        print(f"WARNING: no data at all for {missing} - those axes are being ignored.")
    print(f"\n{'#':>3} {'design':<30}{'comp':>7}{'bind':>7}{'expr':>7}  {'gate':<5} flags")
    print("-" * 84)
    for i, d in enumerate(designs[:top], 1):
        f = lambda v: "  --  " if math.isnan(v) else f"{v:6.3f}"
        print(f"{i:>3} {d.name[:29]:<30}{f(d.composite)}{f(d.bind)}{f(d.express)}  "
              f"{'PASS' if d.passes else 'fail':<5} {'; '.join(d.flags)[:24]}")
    if npass == 0:
        print("\nNo design clears every gate. The gates come from a single binder and are\n"
              "deliberately strict - rank by composite and take the top of the list instead.")


def selftest():
    import tempfile, os
    rows = [
        # name, protenix, spread, esmfold, soldelta -- row A is the l79 profile
        ("binderlike", 0.949, 0.0006, 0.8004, 0.05),
        ("goodbind_badexpr", 0.951, 0.0005, 0.50, -0.20),
        ("badbind_goodexpr", 0.70, 0.30, 0.88, 0.30),
        ("mediocre", 0.85, 0.05, 0.70, 0.00),
        ("missing_expr", 0.94, 0.008, "", ""),
    ]
    fd, p = tempfile.mkstemp(suffix=".csv"); os.close(fd)
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "protenix_iptm", "protenix_seed_spread", "esmfold_iptm",
                    "solublempnn_delta"])
        w.writerows(rows)
    ds = score(read_designs(p))
    names = [d.name for d in ds]
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        ok = ok and cond

    chk(ds[0].name == "binderlike",
        f"l79-like profile ranks #1 (got {names[0]})")
    bl = next(d for d in ds if d.name == "binderlike")
    chk(bl.passes, "l79-like profile clears every gate (gates must never exclude it)")
    gb = next(d for d in ds if d.name == "goodbind_badexpr")
    chk(gb.bind > gb.express, "good-bind/bad-express scores higher on bind than express")
    bb = next(d for d in ds if d.name == "badbind_goodexpr")
    chk(bb.express > bb.bind, "bad-bind/good-express scores higher on express than bind")
    chk(not bb.passes, "low protenix + high spread fails the gates")
    me = next(d for d in ds if d.name == "missing_expr")
    chk(not math.isnan(me.bind) and math.isnan(me.express),
        "a design with no expression metrics still gets a bind score")
    chk("esmfold_iptm:missing" in me.gates_failed, "missing metric is reported as a gate failure")
    # lower-is-better direction
    chk(bl.pct["protenix_seed_spread"] > bb.pct["protenix_seed_spread"],
        "seed spread is scored lower-is-better")
    # ties
    tie = percentile_rank([1.0, 1.0, 2.0], lower_better=False)
    chk(tie[0] == tie[1], "ties receive equal percentile")
    os.unlink(p)
    print("\nSELFTEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("designs", nargs="?", help="CSV of designs to rank")
    ap.add_argument("-o", "--out", default="consensus_ranked.csv")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--calibrate", metavar="LABELLED_CSV",
                    help="recompute gates from a CSV with a bound=1/0 column")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.calibrate:
        new = calibrate(a.calibrate)
        print("Recalibrated gates (paste into GATES at the top of this file):")
        print(json.dumps(new, indent=2))
        GATES.update(new)
    if not a.designs:
        ap.error("need a designs CSV (or --selftest)")
    ds = score(read_designs(a.designs))
    report(ds, a.top)
    write(ds, a.out)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()

# ----------------------------------------------------------------------------
# METHODS
# Outcomes: assay_loading and binding from the two Adaptyv BLI packages
#   (15 designs 2026-07-16, 20 designs 2026-09-15). "Loaded" = the design
#   produced 10 measured response curves; "not loaded" = zero curves.
# Metrics: 5G51_FINAL_20_DOCUMENTED.csv (protenix_ipTM, protenix_seed_spread,
#   esmfold2_ipTM, ipSAE_min) and exports/solublempnn_scores_23designs.csv.
# Tests: Mann-Whitney U two-sided, Spearman rho, AUC = U/(n1*n0).
# CAVEAT: one design bound, out of 35. The binding axis rests on that single
#   observation and its ranks were computed after the fact. The expression
#   axis has 17-18 outcomes and NOTHING reaches p<0.05. This script encodes a
#   working hypothesis, not a validated model. Run --calibrate on every new
#   batch of ground truth.
# ----------------------------------------------------------------------------
