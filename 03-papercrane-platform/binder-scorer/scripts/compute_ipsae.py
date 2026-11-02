#!/usr/bin/env python3
"""ipSAE from the saved PAE matrices — head-to-head vs iptm on all 5 targets.

ipSAE (Dunbrack 2025): restrict to cross-chain interface (pae<cutoff), use a
per-residue LOCAL d0 from each residue's interface-partner count, ptm-transform,
mean over partners, MAX over residues, MAX over the two chain directions. Fixes
iptm's two failure modes (monomer dilution + length-inflated d0). cutoff=10 (Boltz).
"""
from __future__ import annotations
import glob, json, os, sys
import numpy as np
import gemmi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs   # noqa: E402
from scorer.metric_power import _auc          # noqa: E402

TARGETS = ["PDL1", "MDM2", "INSULINR", "EGFR", "IL7R"]
CUTOFF = 10.0
K = 20


def calc_d0(L):
    L = float(L)
    d0 = 1.24 * (L - 15) ** (1.0 / 3.0) - 1.8 if L > 27 else 1.0
    return max(1.0, d0)


def ptm(x, d0):
    return 1.0 / (1.0 + (x / d0) ** 2)


def chain_lengths(cif):
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    if "A" not in ch or "B" not in ch:
        return None
    return sum(1 for _ in ch["A"]), sum(1 for _ in ch["B"])


def ipsae(pae, L_t, L_b, cutoff=CUTOFF):
    N = L_t + L_b
    if pae.shape[0] != N:           # PAE/residue mismatch -> skip
        return None
    A = np.zeros(N, bool); A[:L_t] = True
    B = ~A

    def direction(src, dst):
        best = 0.0
        valid_dst = dst
        for i in np.where(src)[0]:
            vp = valid_dst & (pae[i] < cutoff)
            n0 = int(vp.sum())
            if n0 == 0:
                continue
            d0 = calc_d0(n0)
            val = ptm(pae[i][vp], d0).mean()
            if val > best:
                best = val
        return best
    return max(direction(A, B), direction(B, A))


def main():
    print(f"{'target':9}{'n':>5}{'bind%':>7}   {'iptm_AUC':>9}{'ipSAE_AUC':>10}   "
          f"{'iptm_P@20':>10}{'ipSAE_P@20':>11}  winner")
    for t in TARGETS:
        designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
                   if d["target"].upper() == t}
        rows = []
        for d in glob.glob(f"/tmp/{t.lower()}_folds/{t}_*"):
            cif = os.path.join(d, "outputs/files/prediction/sample_0_predicted_structure.cif")
            paef = os.path.join(d, "outputs/files/prediction/sample_0_pae.npz")
            mj = os.path.join(d, "outputs/files/prediction/metrics.json")
            did = f"{t}:" + os.path.basename(d).split("_", 1)[1]
            if not all(os.path.exists(x) for x in (cif, paef, mj)) or did not in designs:
                continue
            cl = chain_lengths(cif)
            if cl is None:
                continue
            pae = np.load(paef)["pae"]
            isae = ipsae(pae, cl[0], cl[1])
            if isae is None:
                continue
            met = json.load(open(mj))["best_sample"]["metrics"]
            rows.append({"binds": designs[did]["binds"], "iptm": met["iptm"], "ipsae": isae})
        if not rows:
            print(f"{t:9} no data"); continue
        n = len(rows); npos = sum(r["binds"] for r in rows)

        def auc(k):
            return _auc([(r[k], r["binds"]) for r in rows])

        def patk(k):
            s = sorted(rows, key=lambda r: -r[k])[:K]
            return sum(1 for r in s if r["binds"]) / K
        ia, sa = auc("iptm"), auc("ipsae")
        ip, sp = patk("iptm"), patk("ipsae")
        win = "ipSAE" if sa > ia else ("iptm" if ia > sa else "tie")
        print(f"{t:9}{n:>5}{npos/n:>7.0%}   {ia:>9.3f}{sa:>10.3f}   "
              f"{int(round(ip*K)):>8}/20{int(round(sp*K)):>9}/20  {win}")


if __name__ == "__main__":
    main()
