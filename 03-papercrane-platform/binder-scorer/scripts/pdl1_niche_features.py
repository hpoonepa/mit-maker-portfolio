#!/usr/bin/env python3
"""Compute the LLM's PD-L1-specific niche features from the 177 cached structures.

Tests whether literature-derived FIT-QUALITY geometry (burial, complementarity,
charge match, hotspot contacts) adds signal BEYOND the best generic metric (iptm).
No new folding — reuses /tmp/pdl1_folds CIFs.
"""
from __future__ import annotations
import csv, glob, json, os, sys
import numpy as np
import gemmi
from scipy.spatial import cKDTree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs   # noqa: E402
from scorer.metric_power import _auc          # noqa: E402

OFFSET = 18
CONTACT = 5.0
TIGHT = 4.0
CHARGE = {"ASP": -1, "GLU": -1, "LYS": 1, "ARG": 1, "HIS": 0.5}
EPI = set(json.load(open(os.path.join(REPO, "data/processed/llm_priors.json")))["PDL1"]["epitope_residues"])


def heavy(res):
    return [a for a in res if not a.element.is_hydrogen]


def features_from_cif(path):
    st = gemmi.read_structure(path)
    m = st[0]
    chains = {ch.name: ch for ch in m}
    A, B = chains.get("A"), chains.get("B")
    if A is None or B is None:
        return None
    # binder atoms + per-atom residue id/charge
    bpos, bres, bcharge = [], [], []
    for ri, res in enumerate(B):
        c = CHARGE.get(res.name, 0)
        for a in heavy(res):
            bpos.append([a.pos.x, a.pos.y, a.pos.z]); bres.append(ri); bcharge.append(c)
    bpos = np.array(bpos); tree = cKDTree(bpos)
    bres = np.array(bres); bcharge = np.array(bcharge)

    buried_atoms = tight_atoms = 0
    contacted_res = set()           # target full-residue numbers contacted
    res_pairs = set()               # (target_full, binder_res) contacting pairs
    pair_charge = {}                # (t_full,b_res) -> (t_charge,b_charge)
    mind_list = []
    for ti, res in enumerate(A, start=1):
        full = ti + OFFSET
        tcharge = CHARGE.get(res.name, 0)
        res_buried = False
        for a in heavy(res):
            idxs = tree.query_ball_point([a.pos.x, a.pos.y, a.pos.z], CONTACT)
            if idxs:
                buried_atoms += 1; res_buried = True
                d, _ = tree.query([a.pos.x, a.pos.y, a.pos.z])
                mind_list.append(d)
                if d < TIGHT:
                    tight_atoms += 1
                for bi in idxs:
                    key = (full, int(bres[bi]))
                    if key not in res_pairs:
                        res_pairs.add(key); pair_charge[key] = (tcharge, bcharge[bi])
        if res_buried:
            contacted_res.add(full)

    n_contact = len(contacted_res)
    hotspot = len(contacted_res & EPI)
    # charge complementarity: + when opposite charges contact
    charge_comp = sum(-tc * bc for (tc, bc) in pair_charge.values())
    # complementarity / packing proxy: fraction of buried atoms in TIGHT contact (tighter = better fit)
    packing = (tight_atoms / buried_atoms) if buried_atoms else 0.0
    return {
        "beta_sheet_interface_burial": buried_atoms,      # # target atoms buried
        "hotspot_residue_contact_count": hotspot,         # contacts on PD-1 hotspots
        "flat_epitope_complementarity": packing,          # tight-contact fraction (fit quality)
        "charge_complementarity": charge_comp,            # favorable electrostatics
        "n_contact_res": n_contact,
        "epitope_burial": sum(1 for r in contacted_res if r in EPI) / len(EPI),
    }


def main():
    designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
               if d["target"].upper() == "PDL1"}
    uni = {r["design_id"]: r for r in csv.DictReader(open("data/processed/pdl1_uniform_boltz.csv"))}
    rows = []
    for d in glob.glob("/tmp/pdl1_folds/PDL1_*"):
        cif = os.path.join(d, "outputs/files/prediction/sample_0_predicted_structure.cif")
        did = "PDL1:" + os.path.basename(d).split("_", 1)[1]
        if not os.path.exists(cif) or did not in designs:
            continue
        f = features_from_cif(cif)
        if f is None:
            continue
        f["design_id"] = did; f["binds"] = designs[did]["binds"]
        f["iptm"] = float(uni[did]["iptm"]) if did in uni else None
        rows.append(f)
    npos = sum(r["binds"] for r in rows)
    print(f"computed niche features for {len(rows)} PDL1 designs, {npos} binders\n")

    FEATS = ["beta_sheet_interface_burial", "hotspot_residue_contact_count",
             "flat_epitope_complementarity", "charge_complementarity",
             "n_contact_res", "epitope_burial"]

    def auc(key):
        p = [(r[key], r["binds"]) for r in rows if r[key] is not None]
        return _auc(p)

    def patk(score_of, kk=20):
        s = sorted((r for r in rows if score_of(r) is not None), key=lambda r: -score_of(r))
        top = s[:kk]
        return sum(1 for r in top if r["binds"]) / len(top)

    print("=== niche feature ALONE (binders vs non-binders) ===")
    print(f"{'feature':34}{'AUC':>7}{'P@20':>7}  binders_in_top20")
    for k in FEATS:
        a = auc(k); p = patk(lambda r, k=k: r[k])
        print(f"{k:34}{a:>7.3f}{p:>7.3f}      {int(round(p*20))}/20")

    # does adding the best niche feature to iptm beat iptm alone?
    def z(key):
        v = np.array([r[key] if r[key] is not None else np.nan for r in rows], float)
        mu, sd = np.nanmean(v), np.nanstd(v)
        return {id(r): (0.0 if not np.isfinite(x) else (x - mu) / sd) for r, x in zip(rows, v)}
    zi = z("iptm")
    print("\n=== iptm ALONE vs iptm + niche feature (P@20, /20) ===")
    base = patk(lambda r: zi[id(r)])
    print(f"  iptm alone                         {base:.3f}   {int(round(base*20))}/20")
    for k in FEATS:
        zk = z(k)
        for w in [0.3, 0.6, 1.0]:
            p = patk(lambda r, zk=zk, w=w: zi[id(r)] + w * zk[id(r)])
            tag = "  <-- beats iptm" if p > base else ""
            print(f"  iptm + {w:.1f}*{k:30} {p:.3f}   {int(round(p*20))}/20{tag}")


if __name__ == "__main__":
    main()
