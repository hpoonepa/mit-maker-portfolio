#!/usr/bin/env python3
"""Generalized niche-vs-generic test for any folded target.

Usage: PYTHONPATH=. python3 scripts/analyze_target.py MDM2
Computes uniform Boltz metrics + LEAN niche features from cached CIFs, then asks:
does a lean niche-augmented model beat the best generic metric alone?
"""
from __future__ import annotations
import csv, glob, json, os, re, sys
import numpy as np
import gemmi
from scipy.spatial import cKDTree
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs, synth_design_id   # noqa: E402
from scorer.metric_power import _auc                           # noqa: E402

TARGET = sys.argv[1].upper() if len(sys.argv) > 1 else "MDM2"
CACHE = f"/tmp/{TARGET.lower()}_folds"
CONTACT, TIGHT = 5.0, 4.0
CHARGE = {"ASP": -1, "GLU": -1, "LYS": 1, "ARG": 1, "HIS": 0.5}
AROM = {"PHE", "TRP", "TYR"}
HYDRO = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP"}


def offset_and_epi():
    txt = open(os.path.join(REPO, "data/raw/target_references.fasta")).read()
    off = 0
    for b in re.split(r"^>", txt, flags=re.M):
        if b.upper().startswith(TARGET):
            m = re.search(r"(\d+)-(\d+)", b.split("\n")[0]); off = int(m.group(1)) - 1 if m else 0
    epi = set(int(r) for r in json.load(open(os.path.join(REPO, "data/processed/llm_priors.json")))[TARGET]["epitope_residues"])
    return off, epi


def niche(cif, epi, offset):
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    A, B = ch.get("A"), ch.get("B")
    if not A or not B:
        return None
    bpos, bres, bcharge, bname = [], [], [], []
    for ri, res in enumerate(B):
        for a in res:
            if a.element.is_hydrogen:
                continue
            bpos.append([a.pos.x, a.pos.y, a.pos.z]); bres.append(ri)
            bcharge.append(CHARGE.get(res.name, 0)); bname.append(res.name)
    tree = cKDTree(np.array(bpos)); bres = np.array(bres); bcharge = np.array(bcharge)
    buried = tight = 0
    contacted, pairs, pair_q = set(), set(), {}
    arom_anchor, hydro_anchor = set(), set()
    for ti, res in enumerate(A, start=1):
        full = ti + offset; is_epi = full in epi; tq = CHARGE.get(res.name, 0)
        rb = False
        for a in res:
            if a.element.is_hydrogen:
                continue
            idx = tree.query_ball_point([a.pos.x, a.pos.y, a.pos.z], CONTACT)
            if idx:
                buried += 1; rb = True
                d, _ = tree.query([a.pos.x, a.pos.y, a.pos.z])
                if d < TIGHT:
                    tight += 1
                for bi in idx:
                    k = (full, int(bres[bi]))
                    if k not in pairs:
                        pairs.add(k); pair_q[k] = (tq, bcharge[bi])
                    if is_epi and bname[bi] in AROM:
                        arom_anchor.add(int(bres[bi]))
                    if is_epi and bname[bi] in HYDRO:
                        hydro_anchor.add(int(bres[bi]))
        if rb:
            contacted.add(full)
    n = len(contacted)
    return {
        "hotspot_contacts": len(contacted & epi),
        "interface_burial": buried,
        "complementarity": (tight / buried) if buried else 0.0,
        "charge_comp": sum(-tc * bc for tc, bc in pair_q.values()),
        "aromatic_anchor": len(arom_anchor),      # binder aromatics in the epitope (triad mimicry)
        "hydrophobic_anchor": len(hydro_anchor),
        "n_contact": n,
    }


def main():
    off, epi = offset_and_epi()
    designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
               if d["target"].upper() == TARGET}
    rows = []
    for d in glob.glob(f"{CACHE}/{TARGET}_*"):
        cif = os.path.join(d, "outputs/files/prediction/sample_0_predicted_structure.cif")
        mj = os.path.join(d, "outputs/files/prediction/metrics.json")
        did = f"{TARGET}:" + os.path.basename(d).split("_", 1)[1]
        if not (os.path.exists(cif) and os.path.exists(mj)) or did not in designs:
            continue
        nf = niche(cif, epi, off)
        if not nf:
            continue
        met = json.load(open(mj))["best_sample"]["metrics"]
        r = {"binds": designs[did]["binds"], "iptm": met["iptm"], "ptm": met["ptm"],
             "complex_iplddt": met["complex_iplddt"], "complex_ipde": -met["complex_ipde"],
             "structure_confidence": met["structure_confidence"]}
        r.update(nf); rows.append(r)
    npos = sum(r["binds"] for r in rows); n = len(rows)
    K = 20
    print(f"{TARGET}: {n} designs, {npos} binders ({npos/n:.0%}), random P@20 ~ {20*npos/n:.0f}/20\n")

    GENERIC = ["iptm", "ptm", "complex_iplddt", "complex_ipde", "structure_confidence"]
    NICHE = ["hotspot_contacts", "interface_burial", "complementarity", "charge_comp", "aromatic_anchor", "hydrophobic_anchor", "n_contact"]

    def auc(key):
        return _auc([(r[key], r["binds"]) for r in rows])

    print("=== single-feature AUC ===")
    allf = sorted(GENERIC + NICHE, key=lambda k: -abs(auc(k) - 0.5))
    for k in allf:
        tag = "generic" if k in GENERIC else "niche"
        print(f"  {k:22}{auc(k):.3f}  [{tag}]")
    best_generic = max(GENERIC, key=lambda k: abs(auc(k) - 0.5))
    print(f"\nbest generic = {best_generic} (AUC {auc(best_generic):.3f})")

    def patk(scores):
        return sum(1 for i in np.argsort(-np.array(scores))[:K] if rows[i]["binds"]) / K

    def lr_cv(feats):
        X = np.array([[r[k] for k in feats] for r in rows]); y = np.array([int(r["binds"]) for r in rows])
        oof = np.zeros(n)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(X, y):
            sc = StandardScaler().fit(X[tr])
            oof[te] = LogisticRegression(max_iter=1000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr]).predict_proba(sc.transform(X[te]))[:, 1]
        return patk(oof)

    # LEAN 6: best generic + top-5 niche by |AUC-0.5|
    niche_ranked = sorted(NICHE, key=lambda k: -abs(auc(k) - 0.5))
    lean = [best_generic] + niche_ranked[:5]
    p_gen = patk([r[best_generic] for r in rows])
    print(f"\n=== TOP-20 binders caught (the bar = best generic alone) ===")
    print(f"  {best_generic} alone .............. {int(round(p_gen*K))}/20")
    print(f"  LEAN-6 (LR 5-fold CV) ......... {int(round(lr_cv(lean)*K))}/20   feats={lean}")
    print(f"  generics-only (LR CV) ......... {int(round(lr_cv(GENERIC)*K))}/20")
    print(f"  ALL features (LR CV) .......... {int(round(lr_cv(GENERIC+NICHE)*K))}/20")
    print(f"  niche-only (LR CV) ............ {int(round(lr_cv(NICHE)*K))}/20")


if __name__ == "__main__":
    main()
