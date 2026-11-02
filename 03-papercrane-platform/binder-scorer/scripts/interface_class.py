#!/usr/bin/env python3
"""Structural interface_class: cleft-vs-flat from binder ENGULFMENT.

Fixes the broken sequence-based interface_class (which labeled everything
'sheet_flat'). For each folded complex, measure how much the target wraps around
the binder at the interface:

  For each binder interface atom, take unit vectors to nearby target atoms and
  average them. Flat face -> target atoms on ONE side -> vectors align -> large
  resultant. Cleft -> target SURROUNDS the binder -> vectors cancel -> small
  resultant. engulfment = 1 - |mean(unit vectors)|  (0=flat, 1=fully engulfed).

Median across a target's designs = a robust architecture score. No labels used.
Validation: MDM2 (p53 cleft) should score highest; PDL1/IL7R/EGFR/INSULINR (flat
Ig faces) lower.
"""
from __future__ import annotations
import glob, os, sys
import numpy as np
import gemmi
from scipy.spatial import cKDTree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["MDM2", "PDL1", "IL7R", "EGFR", "INSULINR"]
CONTACT = 5.0      # interface atom: within this of target
NEIGH_R = 10.0     # radius for the engulfment cone
SAMPLE = 40        # designs per target (engulfment is stable; subsample for speed)
CLEFT_T = 0.31     # gap midpoint: flat Ig faces cluster ~0.26-0.28, MDM2 cleft ~0.35


def engulfment(cif):
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    A, B = ch.get("A"), ch.get("B")
    if not A or not B:
        return None
    tpos = np.array([[a.pos.x, a.pos.y, a.pos.z] for r in A for a in r if not a.element.is_hydrogen])
    bpos = np.array([[a.pos.x, a.pos.y, a.pos.z] for r in B for a in r if not a.element.is_hydrogen])
    if len(tpos) < 10 or len(bpos) < 10:
        return None
    ttree = cKDTree(tpos)
    vals = []
    for p in bpos:
        near = ttree.query_ball_point(p, CONTACT)
        if not near:
            continue  # not an interface atom
        cone = ttree.query_ball_point(p, NEIGH_R)
        if len(cone) < 4:
            continue
        v = tpos[cone] - p
        v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
        resultant = np.linalg.norm(v.mean(axis=0))   # 1=one-sided, ~0=surrounded
        vals.append(1.0 - resultant)
    return float(np.mean(vals)) if vals else None


def main():
    print(f"{'target':10}{'n_complexes':>12}{'engulfment(med)':>17}{'IQR':>14}   class")
    rows = []
    for t in TARGETS:
        cifs = sorted(glob.glob(f"/tmp/{t.lower()}_folds/{t}_*/outputs/files/prediction/sample_0_predicted_structure.cif"))[:SAMPLE]
        scores = [s for s in (engulfment(c) for c in cifs) if s is not None]
        if not scores:
            print(f"{t:10}{'no folds':>12}")
            continue
        med = float(np.median(scores))
        q1, q3 = np.percentile(scores, 25), np.percentile(scores, 75)
        cls = "sharp-cleft" if med >= CLEFT_T else "flat-sheet"
        rows.append((t, med, cls))
        print(f"{t:10}{len(scores):>12}{med:>17.3f}{f'[{q1:.2f},{q3:.2f}]':>14}   {cls}")
    rows.sort(key=lambda r: -r[1])
    print("\nranked by cleftness:", " > ".join(f"{t}({m:.2f})" for t, m, _ in rows))
    top = rows[0][0] if rows else None
    print(f"\nVALIDATION: most cleft-like = {top}  (expected MDM2). "
          f"{'PASS' if top == 'MDM2' else 'CHECK'}")


if __name__ == "__main__":
    main()
