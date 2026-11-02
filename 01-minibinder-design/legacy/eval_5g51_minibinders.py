#!/usr/bin/env python3
"""Evaluate 5G51 (DWV VP3) minibinders: Boltz2 metrics + LLM per-target prior.

For every folded binder complex in /tmp/5g51_minibinders_folds it computes:
  - Boltz2 confidence: iptm, ptm, complex_plddt/iplddt/pde/ipde (metrics.json)
  - ipSAE (Dunbrack 2025) from the saved PAE matrix
  - hotspot hits I405/F408/I411 (CIF chain-A residues 146/149/152), interface
    residue count, total contacts (5A heavy-atom)
  - binder sequence features: aromatic_fraction, topology_loop_frac, aggregation
Then ranks by the 5G51 LLM prior (data/processed/5g51_prior.json), z-scoring each
weighted metric within the folded set (signed weights; missing metric -> 0;
actifptm proxied by iptm, shape_complementarity omitted). Writes a ranked CSV and
prints a quality assessment.  Safe to run mid-fold (uses whatever is complete).

    python3 eval_5g51_minibinders.py"""
from __future__ import annotations
import csv, glob, json, math, os, statistics, sys

import numpy as np
import gemmi

HERE = os.path.dirname(os.path.abspath(__file__))
BINDER_SCORER = os.path.join(os.path.dirname(HERE), "mosaic", "papercrane", "binder-scorer")
sys.path.insert(0, BINDER_SCORER)
from scorer.biology_features import aggregation_propensity, topology_loop_frac  # noqa: E402

CACHE = "/tmp/5g51_minibinders_folds"
FASTA = os.path.join(HERE, "VP3_5MV5_all_minibinders.fasta")
PRIOR = os.path.join(BINDER_SCORER, "data", "processed", "5g51_prior.json")
OUT = os.path.join(HERE, "5g51_minibinder_scored.csv")
HOTSPOTS = {146, 149, 152}       # I405/F408/I411 in CIF chain-A numbering (offset 259)
CONTACT_A = 5.0
CUTOFF = 10.0

# metric key (in the LLM prior) -> feature name we computed. actifptm proxied by
# iptm (closest available contact-confidence metric); shape_complementarity omitted.
PRIOR_KEY_MAP = {
    "computational__actifptm": "iptm",
    "computational__interface_residues": "interface_residues",
    "computational__boltz2_min_ipsae": "ipsae",
    "aromatic_fraction": "aromatic_fraction",
    "bio__topology_loop_frac": "topology_loop_frac",
    "bio__aggregation_propensity": "aggregation_propensity",
}


def calc_d0(L):
    L = float(L)
    return max(1.0, 1.24 * (L - 15) ** (1.0 / 3.0) - 1.8 if L > 27 else 1.0)


def _ptm(x, d0):
    return 1.0 / (1.0 + (x / d0) ** 2)


def ipsae(pae, Lt, Lb):
    N = Lt + Lb
    if pae.shape[0] != N:
        return None
    A = np.zeros(N, bool); A[:Lt] = True; B = ~A

    def direction(src, dst):
        best = 0.0
        for i in np.where(src)[0]:
            vp = dst & (pae[i] < CUTOFF)
            if int(vp.sum()) == 0:
                continue
            v = _ptm(pae[i][vp], calc_d0(int(vp.sum()))).mean()
            best = max(best, v)
        return best
    return max(direction(A, B), direction(B, A))


def aromatic_fraction(seq):
    return sum(seq.count(a) for a in "FWY") / len(seq) if seq else 0.0


def read_fasta():
    name, seq, out = None, [], {}
    for ln in open(FASTA):
        ln = ln.rstrip("\n")
        if ln.startswith(">"):
            if name and seq:
                out[name] = "".join(seq)
            name = ln[1:].split()[0]; seq = []
        elif ln:
            seq.append(ln.strip())
    if name and seq:
        out[name] = "".join(seq)
    return out


def contacts(cif):
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    A, B = ch.get("A"), ch.get("B")
    if A is None or B is None:
        return None
    bpts = [a.pos for r in B for a in r if not a.element.is_hydrogen]
    if not bpts:
        return None
    contacted = set()
    for i, res in enumerate(A, start=1):
        if any(min(a.pos.dist(p) for p in bpts) <= CONTACT_A
               for a in res if not a.element.is_hydrogen):
            contacted.add(i)
    return (len(HOTSPOTS & contacted), len(contacted), len(bpts),
            sum(1 for _ in A), sum(1 for _ in B))


def zscore(vals):
    vals = [float(v) if (v is not None and math.isfinite(float(v))) else None for v in vals]
    fin = [v for v in vals if v is not None]
    if not fin:
        return [0.0] * len(vals)
    mu = statistics.fmean(fin)
    sd = statistics.pstdev(fin)
    if sd == 0:
        return [0.0] * len(vals)
    return [((v - mu) / sd) if v is not None else 0.0 for v in vals]


def main():
    seqs = read_fasta()
    weights = json.load(open(PRIOR))["5G51"]["weights"]
    rows = []
    for d in sorted(glob.glob(os.path.join(CACHE, "*"))):
        name = os.path.basename(d)
        pred = os.path.join(d, "outputs/files/prediction")
        cif, paef, mj = (os.path.join(pred, f) for f in
                         ("sample_0_predicted_structure.cif", "sample_0_pae.npz", "metrics.json"))
        if not all(os.path.exists(x) for x in (cif, paef, mj)):
            continue
        c = contacts(cif)
        if c is None:
            continue
        hh, iface, _, Lt, Lb = c
        pae = np.load(paef)["pae"]
        isae = ipsae(pae, Lt, Lb)
        met = json.load(open(mj))["best_sample"]["metrics"]
        seq = seqs.get(name, "")
        rows.append({
            "name": name, "campaign": name.split("_")[0] if "_" in name else name,
            "len": Lb, "hotspots_hit": hh, "interface_residues": iface,
            "ipsae": isae, "iptm": met.get("iptm"), "ptm": met.get("ptm"),
            "complex_plddt": met.get("complex_plddt"), "complex_ipde": met.get("complex_ipde"),
            "aromatic_fraction": aromatic_fraction(seq) if seq else None,
            "topology_loop_frac": topology_loop_frac(seq) if seq else None,
            "aggregation_propensity": aggregation_propensity(seq) if seq else None,
        })
    if not rows:
        print("No completed folds yet."); return

    # LLM-prior score: signed weighted sum of z-scored features (missing -> 0).
    zcols = {feat: zscore([r[feat] for r in rows]) for feat in set(PRIOR_KEY_MAP.values())}
    active, total_w = [], 0.0
    for r_i, r in enumerate(rows):
        s = 0.0
        for pkey, feat in PRIOR_KEY_MAP.items():
            if pkey in weights:
                s += weights[pkey] * zcols[feat][r_i]
        r["llm_prior_score"] = s
    for pkey, feat in PRIOR_KEY_MAP.items():
        if pkey in weights:
            active.append(f"{pkey}->{feat} ({weights[pkey]:+.3f})"); total_w += abs(weights[pkey])

    rows.sort(key=lambda r: -r["llm_prior_score"])
    for i, r in enumerate(rows, 1):
        r["llm_rank"] = i

    with open(OUT, "w", newline="") as fh:
        cols = ["llm_rank", "name", "campaign", "len", "llm_prior_score", "hotspots_hit",
                "ipsae", "iptm", "interface_residues", "ptm", "complex_plddt", "complex_ipde",
                "aromatic_fraction", "topology_loop_frac", "aggregation_propensity"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # ---- quality assessment ----
    n = len(rows)
    ipsae_vals = [r["ipsae"] for r in rows if r["ipsae"] is not None]
    strong = [r for r in rows if (r["ipsae"] or 0) >= 0.70 and r["hotspots_hit"] == 3]
    good_ipsae = [r for r in rows if (r["ipsae"] or 0) >= 0.70]
    hh3 = [r for r in rows if r["hotspots_hit"] == 3]
    print(f"\n{'='*70}\n5G51 MINIBINDER EVALUATION  (n={n} folded of 415)\n{'='*70}")
    print(f"LLM prior active weights (|w| sum {total_w:.2f} of 1.0):")
    for a in active:
        print(f"   {a}")
    print(f"\nQUALITY (Boltz2):")
    print(f"  ipSAE >= 0.70 (strong interface):     {len(good_ipsae):>3}/{n}  ({100*len(good_ipsae)/n:.0f}%)")
    print(f"  3/3 hotspots (I405+F408+I411):        {len(hh3):>3}/{n}  ({100*len(hh3)/n:.0f}%)")
    print(f"  BOTH (ipSAE>=0.70 AND 3/3 hotspots):  {len(strong):>3}/{n}  <- top-tier candidates")
    if ipsae_vals:
        print(f"  ipSAE: median {statistics.median(ipsae_vals):.3f}, max {max(ipsae_vals):.3f}")
    print(f"\nTOP 15 BY 5G51 LLM PRIOR:")
    print(f"  {'#':>2} {'name':<26}{'llm':>7}{'ipSAE':>7}{'iptm':>6}{'hs':>3}{'iface':>6}")
    for r in rows[:15]:
        print(f"  {r['llm_rank']:>2} {r['name']:<26}{r['llm_prior_score']:>7.2f}"
              f"{(r['ipsae'] or 0):>7.3f}{(r['iptm'] or 0):>6.2f}{r['hotspots_hit']:>3}{r['interface_residues']:>6}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
