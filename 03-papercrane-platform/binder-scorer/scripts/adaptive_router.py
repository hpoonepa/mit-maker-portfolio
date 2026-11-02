#!/usr/bin/env python3
"""Adaptive niche-vs-generic router. Step 1: find the CEILING (oracle alpha).

For each folded target: generic_composite (z-mean of Boltz confidence metrics) and
niche_composite (z-mean of CONFIDENCE-GATED hotspot + fit-quality features, on a
STRUCTURE-VALIDATED epitope). Router = (1-a)*generic + a*niche. Sweep a in [0,1];
report whether the best a ties-or-beats the best generic on EVERY target.

Confidence gate: per-atom pLDDT (CIF B-factor) — a hotspot contact only counts if
both atoms are confident (>70). Kills the 'Boltz docks non-binders on the epitope'
failure that inverted raw epitope_contact.
Epitope validation: keep only LLM epitope residues that are actually contacted by
>=10% of designs (drops mis-numbered/buried residues — the EGFR failure).
"""
from __future__ import annotations
import csv, glob, json, os, re, sys
import numpy as np
import gemmi
from scipy.spatial import cKDTree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs           # noqa: E402
from scorer.metric_power import _auc                   # noqa: E402
from scripts.compute_ipsae import ipsae, chain_lengths  # noqa: E402

TARGETS = ["PDL1", "MDM2", "INSULINR", "EGFR", "IL7R"]
CONTACT, TIGHT, PLDDT_OK = 5.0, 4.0, 70.0
# ipSAE is a uniformly stronger interface anchor than iptm (research-validated) -> include it
GENERIC = ["ipsae", "iptm", "ptm", "complex_iplddt", "complex_ipde_neg", "structure_confidence"]
K = 20


def offset_and_epi(t):
    txt = open(os.path.join(REPO, "data/raw/target_references.fasta")).read()
    off = 0
    for b in re.split(r"^>", txt, flags=re.M):
        if b.upper().startswith(t):
            m = re.search(r"(\d+)-(\d+)", b.split("\n")[0]); off = int(m.group(1)) - 1 if m else 0
    epi = set(int(r) for r in json.load(open(os.path.join(REPO, "data/processed/llm_priors.json")))[t]["epitope_residues"])
    return off, epi


def parse_contacts(cif, offset):
    """Return (contacted_residues set, raw contact records) for one complex."""
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    A, B = ch.get("A"), ch.get("B")
    if not A or not B:
        return None
    bpos, bpl = [], []
    for res in B:
        for a in res:
            if not a.element.is_hydrogen:
                bpos.append([a.pos.x, a.pos.y, a.pos.z]); bpl.append(a.b_iso)
    tree = cKDTree(np.array(bpos)); bpl = np.array(bpl)
    recs = []  # (full_resnum, confident_bool, tight_bool)
    contacted = set()
    for ti, res in enumerate(A, start=1):
        full = ti + offset; conf = tight = False
        for a in res:
            if a.element.is_hydrogen:
                continue
            d, j = tree.query([a.pos.x, a.pos.y, a.pos.z])
            if d <= CONTACT:
                contacted.add(full)
                if a.b_iso > PLDDT_OK and bpl[j] > PLDDT_OK:
                    conf = True
                if d < TIGHT:
                    tight = True
        if full in contacted:
            recs.append((full, conf, tight))
    return contacted, recs


def load_target(t):
    off, epi = offset_and_epi(t)
    designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
               if d["target"].upper() == t}
    cache = f"/tmp/{t.lower()}_folds"
    raw = []
    freq = {}  # epitope residue -> #designs contacting
    for d in glob.glob(f"{cache}/{t}_*"):
        cif = os.path.join(d, "outputs/files/prediction/sample_0_predicted_structure.cif")
        mj = os.path.join(d, "outputs/files/prediction/metrics.json")
        did = f"{t}:" + os.path.basename(d).split("_", 1)[1]
        if not (os.path.exists(cif) and os.path.exists(mj)) or did not in designs:
            continue
        pc = parse_contacts(cif, off)
        if pc is None:
            continue
        contacted, recs = pc
        paef = os.path.join(d, "outputs/files/prediction/sample_0_pae.npz")
        cl = chain_lengths(cif)
        isae = ipsae(np.load(paef)["pae"], cl[0], cl[1]) if (os.path.exists(paef) and cl) else None
        if isae is None:
            continue
        met = json.load(open(mj))["best_sample"]["metrics"]
        raw.append({"binds": designs[did]["binds"], "recs": recs, "contacted": contacted, "ipsae": isae,
                    "iptm": met["iptm"], "ptm": met["ptm"], "complex_iplddt": met["complex_iplddt"],
                    "complex_ipde_neg": -met["complex_ipde"], "structure_confidence": met["structure_confidence"]})
        for r in contacted & epi:
            freq[r] = freq.get(r, 0) + 1
    nd = len(raw)
    # structure-validate epitope: keep residues contacted by >=10% of designs
    valid_epi = {r for r, c in freq.items() if c >= 0.10 * nd}
    # derive niche features per design on the validated epitope
    for d in raw:
        hot = [(f, conf) for (f, conf, tight) in d["recs"] if f in valid_epi]
        d["hotspot_gated"] = sum(1 for f, conf in hot if conf)        # confident hotspot contacts
        d["interface_burial"] = len(d["contacted"])
        d["complementarity"] = sum(1 for (_, _, tight) in d["recs"] if tight) / max(len(d["recs"]), 1)
    return raw, off, len(epi), len(valid_epi)


def zmean(rows, keys):
    cols = []
    for k in keys:
        v = np.array([r[k] for r in rows], float); mu, sd = v.mean(), v.std()
        cols.append((v - mu) / sd if sd else v * 0)
    return np.mean(cols, axis=0)


def patk(rows, score):
    return sum(1 for i in np.argsort(-score)[:K] if rows[i]["binds"]) / K


def main():
    print(f"{'target':9}{'designs':>8}{'bind%':>7}{'valid_epi':>11}{'bestGenAUC':>12}"
          f"{'gen_P@20':>10}{'oracle_a':>10}{'router_P@20':>12}{'verdict':>9}")
    wins = 0
    for t in TARGETS:
        rows, off, nepi, nvalid = load_target(t)
        n = len(rows); npos = sum(r["binds"] for r in rows)
        gen = zmean(rows, GENERIC)
        niche = zmean(rows, ["hotspot_gated", "interface_burial", "complementarity"])
        best_gen_auc = max(abs(_auc([(r[k], r["binds"]) for r in rows]) - 0.5) for k in GENERIC) + 0.5
        p_gen = patk(rows, gen)
        best_a, best_p = 0.0, p_gen
        for a in np.linspace(0, 1, 11):
            p = patk(rows, (1 - a) * gen + a * niche)
            if p > best_p + 1e-9:
                best_p, best_a = p, a
        ok = best_p >= p_gen - 1e-9
        wins += ok
        print(f"{t:9}{n:>8}{npos/n:>7.0%}{f'{nvalid}/{nepi}':>11}{best_gen_auc:>12.3f}"
              f"{int(round(p_gen*K)):>8}/20{best_a:>10.1f}{int(round(best_p*K)):>10}/20{'  >=gen' if ok else '  LOSE':>9}")
    print(f"\nCEILING: router (best-alpha) >= generic on {wins}/{len(TARGETS)} targets.")
    print("If high alpha helps MDM2 (and a=0 ties the easy ones), the adaptive concept has headroom.")


if __name__ == "__main__":
    main()
