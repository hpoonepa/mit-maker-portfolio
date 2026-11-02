#!/usr/bin/env python3
"""Combine EVERYTHING (uniform Boltz + niche features) on PDL1.

Q: iptm alone gets 17/20. Can the niche features catch the binders it misses?
Tests: LLM-weighted (full menu) + data-optimal (5-fold CV logistic regression).
"""
from __future__ import annotations
import csv, json, os, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.metric_power import _auc                       # noqa: E402
from scripts.pdl1_uniform_experiment import _call          # noqa: E402

# feature -> (direction higher=better, description)
FEATS = {
    "iptm": (1, "interface predicted TM-score: confidence the binder-target interface is correct"),
    "ptm": (1, "predicted TM-score: overall fold confidence"),
    "complex_iplddt": (1, "interface pLDDT: per-atom interface confidence"),
    "complex_ipde": (-1, "interface predicted distance error (LOWER better)"),
    "structure_confidence": (1, "overall structure confidence"),
    "beta_sheet_interface_burial": (1, "# target atoms the binder buries at the flat IgV beta-sheet interface"),
    "hotspot_residue_contact_count": (1, "# PD-1 hotspot residues the binder contacts"),
    "flat_epitope_complementarity": (1, "tight-contact fraction = shape fit quality to the flat epitope"),
    "charge_complementarity": (1, "favorable electrostatic match (opposite charges in contact)"),
    "n_contact_res": (1, "interface size (target residues contacted)"),
    "epitope_burial": (1, "fraction of literature epitope residues buried"),
}


def load():
    rows = list(csv.DictReader(open("data/processed/pdl1_allfeatures.csv")))
    for r in rows:
        r["binds"] = r["binds"].strip().lower() == "true"
        for k in FEATS:
            r[k] = float(r[k]) if r[k] not in ("", "None") else np.nan
    return rows


def patk(rows, scores, k=20):
    order = np.argsort(-np.array(scores))[:k]
    return sum(1 for i in order if rows[i]["binds"]) / k, [i for i in order]


def llm_full_weights(rows):
    lit = json.load(open("data/processed/literature/PDL1.json"))
    abstracts = "\n".join(f"- {a.get('title','')}" for a in lit.get("abstracts", [])[:12])
    menu = "\n".join(f"  - {k}: {d}" for k, (s, d) in FEATS.items())
    prompt = f"""You are a computational protein engineer ranking de novo PD-L1 binder candidates (a validated
cancer-immunotherapy target) for wet-lab validation — standard structure-based therapeutic design. Each
candidate was folded in complex with PD-L1 (Boltz-2.1). You have BOTH generic structure-confidence metrics
AND PD-L1-specific interface-geometry features computed from the predicted structures:

PD-L1 interface/design literature:
{abstracts}

ALL AVAILABLE FEATURES:
{menu}

Set a SIGNED weighting to rank candidates by how likely each is a genuine binder. Output JSON ONLY:
{{"weights": {{<feature>: <signed float; +=higher->more likely binder>}}, "rationale": "<2-3 sentences>"}}
Concentrate on what predicts binding; you may use all or a subset. Never reference experimental labels."""
    raw = _call(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1]; raw = raw[4:] if raw.lstrip().startswith("json") else raw
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


def main():
    rows = load()
    n = len(rows); npos = sum(r["binds"] for r in rows)
    X = np.array([[(r[k] if not np.isnan(r[k]) else 0.0) for k in FEATS] for r in rows])
    y = np.array([1 if r["binds"] else 0 for r in rows])
    print(f"PDL1: {n} designs, {npos} binders. iptm alone = 17/20 (the bar).\n")

    # ---- the LLM's EXACT weights from the earlier uniform-menu run ----
    print("=== LLM weights (earlier uniform-metric menu) ===")
    prev = {'iptm': 0.35, 'ptm': 0.1, 'complex_iplddt': 0.15, 'complex_ipde': -0.1,
            'structure_confidence': 0.05, 'n_contact': 0.05, 'epitope_contact': 0.12, 'epitope_coverage': 0.08}
    print(" ", prev)

    # z-score features (raw; LLM sign encodes direction)
    def zcol(k):
        v = np.array([r[k] if not np.isnan(r[k]) else np.nan for r in rows]); mu, sd = np.nanmean(v), np.nanstd(v)
        return np.nan_to_num((v - mu) / sd) if sd else v * 0
    Z = {k: zcol(k) for k in FEATS}

    iptm_dir = np.array([r["iptm"] for r in rows])
    p_iptm, iptm_top = patk(rows, iptm_dir)

    # ---- re-prompt LLM with the FULL menu (generic + niche); optional (refusals happen) ----
    print("\n=== LLM weights (FULL menu: generic + niche) ===")
    try:
        w = llm_full_weights(rows)
        print("  rationale:", w.get("rationale"))
        print("  weights:", {k: round(v, 3) for k, v in w["weights"].items()})
        llm_score = sum(wt * Z[k] for k, wt in w["weights"].items() if k in Z)
        p_llm, llm_top = patk(rows, llm_score)
    except Exception as e:
        print("  (LLM refused/unavailable:", str(e)[:60], "- skipping LLM arm)")
        p_llm, llm_top = None, None

    # ---- data-optimal: 5-fold CV logistic regression over ALL features ----
    oof = np.zeros(n)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    for tr, te in skf.split(X, y):
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
        oof[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    p_cv, cv_top = patk(rows, oof)

    print("\n=== TOP-20 binders caught (the bar = iptm 17/20) ===")
    print(f"  iptm alone .................. {int(round(p_iptm*20))}/20")
    if p_llm is not None:
        print(f"  LLM-weighted (full menu) .... {int(round(p_llm*20))}/20")
    print(f"  data-optimal LR (5-fold CV) . {int(round(p_cv*20))}/20   <- ceiling of ANY combination")

    # ---- does the combo catch binders iptm missed? ----
    iptm_set = set(iptm_top)
    binders_missed_by_iptm = [i for i in range(n) if rows[i]["binds"] and i not in iptm_set]
    print(f"\n=== iptm's top-20 misses {len(binders_missed_by_iptm)} real binders ===")
    arms = [("LR-CV", cv_top)] + ([("LLM-full", llm_top)] if llm_top is not None else [])
    for tag, top in arms:
        recovered = [i for i in binders_missed_by_iptm if i in set(top)]
        fp_dropped = [i for i in iptm_top if not rows[i]["binds"] and i not in set(top)]
        print(f"  {tag:9}: recovered {len(recovered)} of iptm's missed binders; dropped {len(fp_dropped)} of iptm's 3 false-positives")
    # feature AUCs sorted, to see orthogonality
    print("\n=== single-feature AUC (orthogonality check) ===")
    for k in sorted(FEATS, key=lambda k: -abs(_auc([((r[k]*FEATS[k][0]), r['binds']) for r in rows if not np.isnan(r[k])]) - .5)):
        a = _auc([((r[k]*FEATS[k][0]), r["binds"]) for r in rows if not np.isnan(r[k])])
        print(f"  {k:32}{a:.3f}")


if __name__ == "__main__":
    main()
