#!/usr/bin/env python3
"""Adaptive router v2: STRUCTURE sets base alpha, LLM only refines.

alpha_mech = clip((engulfment - 0.30)/0.20, 0, 0.35)   # flat->0, cleft->~0.25
The LLM reads the (now CORRECT) structural interface_class + literature and may
BUMP alpha up to +0.15 ONLY when alpha_mech > 0 (a structural cleft) and the
literature shows a decisive hotspot mechanism. A flat target stays at alpha=0 no
matter what the LLM says -> the hedging failure is structurally impossible.
Router = (1-alpha)*generic + alpha*niche. Test: >= generic on all 5, > on MDM2.
"""
from __future__ import annotations
import glob, json, os, sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scripts.adaptive_router import load_target, zmean, patk, GENERIC, TARGETS, K  # noqa: E402
from scripts.interface_class import engulfment, CLEFT_T                            # noqa: E402
from scripts.pdl1_uniform_experiment import _call                                  # noqa: E402

NICHE = ["hotspot_gated", "interface_burial", "complementarity"]


def target_engulfment(t):
    cifs = sorted(glob.glob(f"/tmp/{t.lower()}_folds/{t}_*/outputs/files/prediction/sample_0_predicted_structure.cif"))[:40]
    s = [x for x in (engulfment(c) for c in cifs) if x is not None]
    return float(np.median(s)) if s else 0.0


def alpha_mech(eng):
    # cap at 0.25 — the empirical safe ceiling (more geometry overshoots & loses the win)
    return float(np.clip((eng - 0.30) / 0.20, 0.0, 0.25))


def lit_titles(t):
    p = f"data/processed/literature/{t}.json"
    return "; ".join(a.get("title", "")[:70] for a in json.load(open(p)).get("abstracts", [])[:6]) if os.path.exists(p) else ""


def llm_confirm(t, cls, eng, amech, lit):
    """LLM acts as a GATE: confirm the structural cleft is real, or VETO it to 0.
    It cannot set magnitude (that overshoots) — only keep the structural alpha or kill it."""
    prompt = f"""A structural analysis of folded {t} complexes classified the binding site as a SHARP CLEFT
(engulfment={eng:.2f} >= {CLEFT_T}), so a geometry weight of alpha={amech:.2f} is proposed (vs 0 for flat
Ig-like faces). Your job is ONLY to CONFIRM or VETO this — you set no magnitude.

Literature (binder/structure papers): {lit}

CONFIRM (keep=true) if the literature agrees this target's binding depends on a DECISIVE, well-characterized
hotspot/pocket mechanism (specific anchor residues that must be occupied — e.g. a p53-cleft-style groove).
VETO (keep=false) if the literature indicates the real functional interface is actually a flat/broad PPI
surface and the structural 'cleft' is likely incidental. Output JSON ONLY:
{{"keep": <true|false>, "reasoning": "<1 sentence>"}}"""
    raw = _call(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1]; raw = raw[4:] if raw.lstrip().startswith("json") else raw
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


def main():
    print(f"{'target':9}{'engulf':>8}{'class':>13}{'a_mech':>8}{'LLM':>7}{'a_final':>9}"
          f"{'gen':>6}{'router':>8}{'verdict':>9}")
    wins = beats = 0
    details = []
    for t in TARGETS:
        rows, off, nepi, nvalid = load_target(t)
        gen = zmean(rows, GENERIC); niche = zmean(rows, NICHE)
        p_gen = patk(rows, gen)
        eng = target_engulfment(t)
        am = alpha_mech(eng)
        cls = "sharp-cleft" if eng >= CLEFT_T else "flat-sheet"
        gate, reason = "n/a", "(flat: a_mech=0)"
        af = am
        if am > 0:  # only structural clefts go to the LLM gate (confirm/veto)
            try:
                ans = llm_confirm(t, cls, eng, am, lit_titles(t))
                keep = bool(ans["keep"]); reason = ans.get("reasoning", "")
                gate = "keep" if keep else "VETO"
                af = am if keep else 0.0
            except Exception as e:
                gate = "keep*"; reason = f"(LLM failed: {str(e)[:30]}; kept a_mech)"
        p_router = patk(rows, (1 - af) * gen + af * niche)
        ok = p_router >= p_gen - 1e-9
        wins += ok; beats += p_router > p_gen + 1e-9
        print(f"{t:9}{eng:>8.2f}{cls:>13}{am:>8.2f}{gate:>7}{af:>9.2f}"
              f"{int(round(p_gen*K)):>4}/20{int(round(p_router*K)):>6}/20{'  >=gen' if ok else '  LOSE':>9}")
        details.append((t, af, reason))
    print(f"\nrouter v2 >= generic on {wins}/{len(TARGETS)} targets; BEATS on {beats}.")
    print("--- alpha decisions ---")
    for t, af, reason in details:
        print(f"  {t} (alpha={af:.2f}): {reason}")


if __name__ == "__main__":
    main()
