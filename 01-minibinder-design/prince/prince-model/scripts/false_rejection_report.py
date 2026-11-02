#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Aggregate the full-n false-rejection run into the primary result.

Macro-averaged by antigen cluster with a cluster bootstrap, because the
benchmark is cluster-imbalanced: lysozyme and SARS-CoV-2 spike carry hundreds of
deposited antibodies each, and a per-instance mean would be a statement about
which antigens crystallographers liked rather than about the filter. The
resampling unit is the cluster for the same reason.

Also reports the distribution and not only the mean. A mean false-rejection rate
of a few percent is compatible both with the filter nicking one residue off many
epitopes and with it destroying a few epitopes outright, and those are different
products. The "wiped out" row is the one a user would feel.
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path


def _open(path):
    p = str(path)
    return gzip.open(p, "rt") if p.endswith(".gz") else open(p)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("records")
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    recs, errs = [], []
    for line in _open(args.records):
        d = json.loads(line)
        (errs if "err" in d else recs).append(d)

    print(f"{len(recs)} instances judged, {len(errs)} errored")
    if errs:
        c = Counter(e["err"].split(":")[0] for e in errs)
        for k, v in c.most_common(5):
            print(f"    {v:5}  {k}")
        print("  (errors are excluded from the rates below and counted here, "
              "so a shrinking denominator cannot pass as a clean result)")

    by_cluster = defaultdict(list)
    for d in recs:
        by_cluster[d["cluster"]].append(d["n_killed"] / d["n_epitope"])
    clusters = sorted(by_cluster)
    per_cluster = {c: sum(v) / len(v) for c, v in by_cluster.items()}

    macro = sum(per_cluster.values()) / len(per_cluster)
    micro = sum(d["n_killed"] for d in recs) / sum(d["n_epitope"] for d in recs)

    rng = random.Random(args.seed)
    boot = []
    for _ in range(args.n_boot):
        draw = [per_cluster[rng.choice(clusters)] for _ in clusters]
        boot.append(sum(draw) / len(draw))
    boot.sort()
    lo, hi = boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot))]

    untouched = sum(1 for d in recs if d["n_killed"] == 0)
    wiped = sum(1 for d in recs if d["n_killed"] == d["n_epitope"])
    half = sum(1 for d in recs if d["n_killed"] * 2 >= d["n_epitope"])

    print(f"\n{'=' * 70}\nFALSE-REJECTION RATE — fraction of the observed epitope KILLed")
    print(f"{len(recs)} instances, {len(clusters)} antigen clusters\n{'=' * 70}")
    print(f"  macro-average by cluster   {macro:.4f}   95% CI [{lo:.4f}, {hi:.4f}]")
    print(f"                             ({args.n_boot} cluster bootstrap resamples)")
    print(f"  micro (per instance)       {micro:.4f}   "
          f"— dominated by the most-deposited antigens, not a generalisation claim")
    print(f"\n  epitopes untouched         {untouched}/{len(recs)} = {untouched/len(recs):.1%}")
    print(f"  epitopes >=50% killed      {half}/{len(recs)} = {half/len(recs):.2%}")
    print(f"  epitopes entirely killed   {wiped}/{len(recs)} = {wiped/len(recs):.2%}")

    vals = sorted(per_cluster.values())
    print(f"\n  per-cluster rate: median {st.median(vals):.4f}, "
          f"p90 {vals[int(0.9*len(vals))]:.4f}, max {vals[-1]:.4f}")

    reasons = Counter()
    for d in recs:
        for codes in d["reasons"].values():
            reasons.update(codes)
    killed_total = sum(d["n_killed"] for d in recs)
    print(f"\n  why epitope residues were killed ({killed_total} residues):")
    for code, n in reasons.most_common():
        print(f"    {n:7}  {n/max(killed_total,1):6.1%}  {code}")

    worst = sorted(recs, key=lambda d: -d["n_killed"] / d["n_epitope"])[:8]
    print(f"\n  worst instances:")
    for d in worst:
        print(f"    {d['id']:16} {d['n_killed']:3}/{d['n_epitope']:3} "
              f"= {d['n_killed']/d['n_epitope']:.0%}  {d['cluster']}")


if __name__ == "__main__":
    main()
