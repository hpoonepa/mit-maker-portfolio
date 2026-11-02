#!/usr/bin/env python3
"""How good is epitope_contact on PDL1? Within-target AUC + Precision@20.

Compares rankings of PDL1's 177 designs:
  B0              — raw best_ipsae (the trivial baseline; harness P@20 = 0.30)
  epitope_contact — the LLM-epitope structural feature ALONE (no weight tuning)
  B_LLM           — the current PDL1 signed prior
  B_LLM+epitope   — the prior with epitope_contact added (principled weight)

All metrics z-normalized within PDL1 (consistent basis). B0 is rank-invariant to
normalization, so its P@20 matches the LOTO harness exactly = anchor.
"""
from __future__ import annotations
import csv, os, sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs           # noqa: E402
from scorer.metric_power import _auc                  # noqa: E402
from scorer.llm_prior import load_priors              # noqa: E402

K = 20

def metric_val(d, key):
    if key in ("computational__boltz2_min_ipsae", "best_ipsae"):
        return d.get("best_ipsae")
    if key == "epitope_contact":
        return d.get("epitope_contact")
    return d["features"].get(key)

def main():
    designs = [d for d in load_designs("data/processed/labeled_features_bio.csv")
               if d["target"].upper() == "PDL1"]
    ec = {r["design_id"]: float(r["epitope_contact"])
          for r in csv.DictReader(open("data/processed/pdl1_epitope_contact.csv"))}
    for d in designs:
        d["epitope_contact"] = ec.get(d["design_id"])
    n_pos = sum(1 for d in designs if d["binds"])
    have_ec = sum(1 for d in designs if d.get("epitope_contact") is not None)
    print(f"PDL1 designs={len(designs)} binders={n_pos} with_epitope_contact={have_ec}  k={K}\n")

    def auc_within(key):
        pairs = [(metric_val(d, key), d["binds"]) for d in designs]
        pairs = [(s, l) for s, l in pairs if s is not None and s == s]
        return _auc(pairs)

    def prec_at_k(score_fn, k=K):
        scored = [(score_fn(d), d) for d in designs]
        scored = [(s, d) for s, d in scored if s is not None and s == s]
        scored.sort(key=lambda x: -x[0])
        top = scored[:k]
        return sum(1 for _, d in top if d["binds"]) / len(top) if top else float("nan")

    print("=== within-PDL1 discriminative power (AUC; binders vs non-binders) ===")
    for key in ["computational__actifptm", "computational__interface_residues",
                "best_ipsae", "computational__boltz2_iptm", "shape_complementarity",
                "epitope_contact"]:
        a = auc_within(key)
        print(f"  {key:38} AUC={a:.3f}  power={abs(a-0.5)*2:.3f}" if a is not None else f"  {key}: n/a")

    # z-scores within PDL1
    def zmap(key):
        vals = np.array([(metric_val(d, key) if metric_val(d, key) is not None else np.nan)
                         for d in designs], float)
        mu, sd = np.nanmean(vals), np.nanstd(vals)
        if not np.isfinite(sd) or sd == 0:
            return None
        return {id(d): (0.0 if not np.isfinite(v) else (v - mu) / sd)
                for d, v in zip(designs, vals)}

    prior = load_priors("data/processed/llm_priors.json")["PDL1"]

    def bllm(extra=None):
        w = dict(prior.weights)
        if extra:
            w.update(extra)
        zs = {k: zmap(k) for k in w}
        def sc(d):
            return sum(wt * zs[k][id(d)] for k, wt in w.items() if zs[k] is not None)
        return sc

    print("\n=== Precision@20 on PDL1 (higher = better; B0 anchor = 0.30) ===")
    print(f"  B0 (best_ipsae)            {prec_at_k(lambda d: d.get('best_ipsae')):.3f}")
    print(f"  epitope_contact ALONE      {prec_at_k(lambda d: d.get('epitope_contact')):.3f}")
    print(f"  B_LLM (current prior)      {prec_at_k(bllm()):.3f}")
    # principled epitope weight: scale to its discriminative power vs actifptm's
    a_ec = auc_within("epitope_contact"); a_act = auc_within("computational__actifptm")
    top_w = max(abs(v) for v in prior.weights.values())
    epi_w = top_w * (abs(a_ec - 0.5) / max(abs(a_act - 0.5), 1e-9)) if a_ec else 0.0
    print(f"  B_LLM + epitope_contact    {prec_at_k(bllm({'epitope_contact': epi_w})):.3f}   (epitope weight={epi_w:+.3f})")
    # also a sweep so the result isn't a single lucky weight
    print("\n  weight sweep (B_LLM + w*z(epitope_contact)):")
    for w in [0.05, 0.10, 0.20, 0.30, 0.50]:
        print(f"    w={w:.2f}  P@20={prec_at_k(bllm({'epitope_contact': w})):.3f}")

if __name__ == "__main__":
    main()
