#!/usr/bin/env python3
"""Fold all PDL1 designs via Boltz, compute epitope_contact vs the LLM epitope.

Resume-safe: a design whose CIF is already cached is skipped (no re-spend).
Bounded concurrency (server-side parallel). Writes results incrementally and
drops a DONE marker so a detached caller can poll.

epitope_contact(design) = fraction of the binder's target-contact residues that
land on the LLM's literature epitope (PD-1 binding face). A binder that engages
the right face scores high; an off-target binder scores low. This is the
structural feature the LLM's epitope knowledge unlocks — one neither B0 nor the
data models have.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import gemmi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import synth_design_id  # noqa: E402

ORG = "87992dbe-a3b3-4aad-a89e-4ca7064d724c"
CACHE = "/tmp/pdl1_folds"
OUT_CSV = os.path.join(REPO, "data", "processed", "pdl1_epitope_contact.csv")
DONE = os.path.join(REPO, "data", "processed", ".pdl1_epitope.DONE")
OFFSET = 18  # construct position i (1-based) -> full residue i + 18  (PDL1 19-127)
CONTACT_A = 5.0  # heavy-atom contact threshold (Angstrom)
WORKERS = 6


def target_seq() -> str:
    txt = open(os.path.join(REPO, "data/raw/target_references.fasta")).read()
    for b in re.split(r"^>", txt, flags=re.M):
        if b.startswith("PDL1"):
            return "".join(b.split("\n")[1:]).strip()
    raise RuntimeError("PDL1 target not found in target_references.fasta")


def epitope_set() -> set[int]:
    d = json.load(open(os.path.join(REPO, "data/processed/llm_priors.json")))
    return set(int(r) for r in d["PDL1"]["epitope_residues"])


def cif_path(design_id: str) -> str:
    safe = design_id.replace(":", "_")
    return os.path.join(CACHE, safe, "outputs/files/prediction/sample_0_predicted_structure.cif")


def fold_one(design_id: str, tgt: str, binder: str) -> tuple[str, bool, str]:
    """Fold a single complex (resume-safe). Returns (design_id, ok, msg)."""
    out = cif_path(design_id)
    if os.path.exists(out):
        return (design_id, True, "cached")
    run_dir = os.path.join(CACHE, design_id.replace(":", "_"))
    inp = json.dumps({"entities": [
        {"type": "protein", "chain_ids": ["A"], "value": tgt},
        {"type": "protein", "chain_ids": ["B"], "value": binder},
    ]})
    cmd = [
        "boltz-api", "predictions:structure-and-binding", "run",
        "--org", ORG, "--input", inp, "--run-dir", run_dir,
        "--idempotency-key", design_id, "--progress-format", "jsonl",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return (design_id, False, "timeout")
    if os.path.exists(out):
        return (design_id, True, "folded")
    return (design_id, False, f"rc={p.returncode} {p.stderr[-200:]}")


def epitope_contact(design_id: str, epi: set[int]) -> dict | None:
    path = cif_path(design_id)
    if not os.path.exists(path):
        return None
    st = gemmi.read_structure(path)
    m = st[0]
    chains = {ch.name: ch for ch in m}
    A, B = chains.get("A"), chains.get("B")
    if A is None or B is None:
        return None
    bpts = [a.pos for r in B for a in r if not a.element.is_hydrogen]
    contacted = []
    for i, res in enumerate(A, start=1):
        full = i + OFFSET
        hit = any(min((a.pos.dist(p) for p in bpts), default=1e9) <= CONTACT_A
                  for a in res if not a.element.is_hydrogen)
        if hit:
            contacted.append(full)
    n = len(contacted)
    on = [r for r in contacted if r in epi]
    return {
        "design_id": design_id,
        "epitope_contact": (len(on) / n) if n else 0.0,   # frac of footprint on epitope
        "epitope_coverage": len(on) / len(epi) if epi else 0.0,  # frac of epitope touched
        "n_contact": n,
        "n_on_epitope": len(on),
    }


def main() -> None:
    if os.path.exists(DONE):
        os.remove(DONE)
    os.makedirs(CACHE, exist_ok=True)
    tgt = target_seq()
    epi = epitope_set()
    rows = [r for r in csv.DictReader(open(os.path.join(REPO, "data/processed/labeled_features_bio.csv")))
            if r["target"].upper() == "PDL1"]
    jobs = []
    for r in rows:
        seq = r["sequence"].strip()
        did = synth_design_id("PDL1", seq)
        jobs.append((did, seq))
    # dedupe by design_id (same seq -> same id)
    seen, uniq = set(), []
    for did, seq in jobs:
        if did not in seen:
            seen.add(did); uniq.append((did, seq))
    print(f"PDL1 designs: {len(rows)} rows -> {len(uniq)} unique to fold", flush=True)

    done = 0
    fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fold_one, did, tgt, seq): did for did, seq in uniq}
        for f in as_completed(futs):
            did, ok, msg = f.result()
            done += 1
            if not ok:
                fails.append((did, msg))
            if done % 10 == 0 or not ok:
                print(f"[{done}/{len(uniq)}] {did} {'OK' if ok else 'FAIL '+msg}", flush=True)

    # compute epitope_contact for everything that folded
    results = [epitope_contact(did, epi) for did, _ in uniq]
    results = [x for x in results if x]
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["design_id", "epitope_contact", "epitope_coverage", "n_contact", "n_on_epitope"])
        w.writeheader()
        w.writerows(results)
    print(f"\nFolded {len(results)}/{len(uniq)}; {len(fails)} failures.", flush=True)
    if fails:
        print("FAILURES:", fails[:10], flush=True)
    print(f"Wrote {OUT_CSV}", flush=True)
    open(DONE, "w").write(json.dumps({"folded": len(results), "total": len(uniq), "fails": len(fails)}))


if __name__ == "__main__":
    main()
