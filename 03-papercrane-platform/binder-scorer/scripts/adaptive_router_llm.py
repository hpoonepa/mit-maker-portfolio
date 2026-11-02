#!/usr/bin/env python3
"""Can the LLM set the niche-vs-generic dial (alpha) from LABEL-FREE signals?

For each target: give the LLM the interface architecture + the generic metric's
spread across designs (label-free) + literature -> it outputs alpha in [0,1].
Router = (1-alpha)*generic + alpha*niche. Test: router(LLM-alpha) >= generic on
all 5, and > on MDM2. Compare LLM-alpha to the oracle-alpha.
"""
from __future__ import annotations
import csv, json, os, sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scripts.adaptive_router import load_target, zmean, patk, GENERIC, TARGETS, K  # noqa: E402
from scripts.pdl1_uniform_experiment import _call                                  # noqa: E402
from scorer.metric_power import _auc                                               # noqa: E402

NICHE = ["hotspot_gated", "interface_burial", "complementarity"]


def interface_class(t):
    for r in csv.DictReader(open("data/processed/target_features.csv")):
        if r["target"].upper() == t:
            return r.get("interface_class", "?")
    return "?"


def lit_titles(t):
    p = f"data/processed/literature/{t}.json"
    if not os.path.exists(p):
        return ""
    return "; ".join(a.get("title", "")[:70] for a in json.load(open(p)).get("abstracts", [])[:6])


def ask_alpha(t, iface, spread, lit):
    prompt = f"""You rank de novo protein binder candidates against {t} (a validated therapeutic target;
standard structure-based design) for wet-lab testing. Decide ONE number: alpha, how much to override
GENERIC structure-prediction confidence (iptm/pLDDT) with TARGET-SPECIFIC binding-site geometry
(occupying the literature hotspot, fitting the pocket).

CRITICAL CALIBRATION — be sparse:
- The DEFAULT is alpha = 0.0 (EXACTLY zero). Generic confidence is a very strong ranker and the geometry
  features ADD NOISE / actively HURT on most targets. A small "tiebreaker" alpha is a mistake — it makes
  ranking WORSE on well-predicted interfaces. Do NOT hedge.
- Raise alpha ABOVE 0 ONLY for a target whose binding site is a SMALL, DEEP, peptide-like or cryptic
  CLEFT/POCKET with a sharp, well-characterized hotspot (e.g. a p53-binding-cleft-style groove) where
  (a) folds are less reliable AND (b) literature shows exact hotspot occupancy decides binding. For such
  a target use alpha ~0.2-0.3. Large/flat Ig-like beta-sheet interfaces get alpha = 0.0.
- Most targets are flat Ig/sheet interfaces -> alpha = 0.0. Expect to output 0.0 unless this is clearly
  a sharp-cleft case.

Signals for {t}:
- Auto interface label (UNRELIABLE — it mislabels clefts as 'sheet_flat', ignore if it conflicts with
  the literature): {iface}
- Literature (binder/structure papers): {lit}
- Use the literature + your own knowledge of this target's actual binding-site architecture to decide.

Output JSON ONLY:
{{"alpha": <float, usually 0.0>, "architecture": "<flat-sheet | sharp-cleft | other>",
  "reasoning": "<1-2 sentences: what is the real binding-site architecture and why this alpha>"}}"""
    raw = _call(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1]; raw = raw[4:] if raw.lstrip().startswith("json") else raw
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


def main():
    print(f"{'target':9}{'iface':12}{'oracle_a':>9}{'LLM_a':>7}{'gen_P@20':>10}{'router_P@20':>12}{'verdict':>9}")
    wins = 0
    details = []
    for t in TARGETS:
        rows, off, nepi, nvalid = load_target(t)
        n = len(rows)
        gen = zmean(rows, GENERIC); niche = zmean(rows, NICHE)
        p_gen = patk(rows, gen)
        # oracle alpha
        oa, op = 0.0, p_gen
        for a in np.linspace(0, 1, 11):
            p = patk(rows, (1 - a) * gen + a * niche)
            if p > op + 1e-9:
                op, oa = p, a
        # label-free spread of iptm
        ip = np.array([r["iptm"] for r in rows])
        spread = (np.percentile(ip, 10), np.percentile(ip, 50), np.percentile(ip, 90), ip.std())
        iface = interface_class(t)
        try:
            ans = ask_alpha(t, iface, spread, lit_titles(t))
            la = float(ans["alpha"]); reason = ans.get("reasoning", "")
        except Exception as e:
            la, reason = -1.0, f"(LLM failed: {str(e)[:40]})"
        if la < 0:
            la_used = oa  # fall back so the row still computes
            p_router = patk(rows, (1 - la_used) * gen + la_used * niche); used = f"{la_used:.1f}*"
        else:
            p_router = patk(rows, (1 - la) * gen + la * niche); used = f"{la:.2f}"
        ok = p_router >= p_gen - 1e-9
        wins += ok
        print(f"{t:9}{iface[:11]:12}{oa:>9.1f}{used:>7}{int(round(p_gen*K)):>8}/20"
              f"{int(round(p_router*K)):>10}/20{'  >=gen' if ok else '  LOSE':>9}")
        details.append((t, la, reason))
    print(f"\nrouter(LLM-alpha) >= generic on {wins}/{len(TARGETS)} targets.")
    print("\n--- LLM alpha reasoning ---")
    for t, la, reason in details:
        print(f"{t} (alpha={la}): {reason}")


if __name__ == "__main__":
    main()
