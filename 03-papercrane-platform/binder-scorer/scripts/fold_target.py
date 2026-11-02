#!/usr/bin/env python3
"""Fold all designs for a TARGET via Boltz; compute epitope_contact. Resume-safe.

Usage: PYTHONPATH=. python3 scripts/fold_target.py MDM2
Generalizes fold_pdl1_epitope.py: construct + offset from target_references.fasta,
epitope residues from llm_priors.json.
"""
from __future__ import annotations
import csv, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import gemmi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import synth_design_id  # noqa: E402

WORKSPACE = "ws_8pN1jAvRejXlTTrXILXm"  # Default workspace on the credited account
CONTACT_A = 5.0
WORKERS = int(os.environ.get("FOLD_WORKERS", "6"))
MAX_DESIGNS = int(os.environ["MAX_DESIGNS"]) if os.environ.get("MAX_DESIGNS") else None

# load BOLTZ_API_KEY from .env so the CLI (which reads $BOLTZ_API_KEY) authenticates
# against the credited account instead of the exhausted OAuth org.
if not os.environ.get("BOLTZ_API_KEY"):
    _envp = os.path.join(REPO, ".env")
    if os.path.exists(_envp):
        for _l in open(_envp):
            if _l.startswith("BOLTZ_API_KEY="):
                os.environ["BOLTZ_API_KEY"] = _l.split("=", 1)[1].strip()
TARGET = sys.argv[1].upper() if len(sys.argv) > 1 else "MDM2"
CACHE = f"/tmp/{TARGET.lower()}_folds"
OUT_CSV = os.path.join(REPO, f"data/processed/{TARGET.lower()}_epitope_contact.csv")
DONE = os.path.join(REPO, f"data/processed/.{TARGET.lower()}_epitope.DONE")


def target_seq_and_offset():
    txt = open(os.path.join(REPO, "data/raw/target_references.fasta")).read()
    for b in re.split(r"^>", txt, flags=re.M):
        if b.upper().startswith(TARGET):
            hdr = b.split("\n")[0]
            seq = "".join(b.split("\n")[1:]).strip()
            m = re.search(r"(\d+)-(\d+)", hdr)
            offset = int(m.group(1)) - 1 if m else 0
            return seq, offset
    raise RuntimeError(f"{TARGET} not in target_references.fasta")


def epitope_set():
    d = json.load(open(os.path.join(REPO, "data/processed/llm_priors.json")))
    return set(int(r) for r in d[TARGET]["epitope_residues"])


def cif_path(did):
    return os.path.join(CACHE, did.replace(":", "_"), "outputs/files/prediction/sample_0_predicted_structure.cif")


def fold_one(did, tgt, binder):
    out = cif_path(did)
    if os.path.exists(out):
        return (did, True, "cached")
    run_dir = os.path.join(CACHE, did.replace(":", "_"))
    inp = json.dumps({"entities": [
        {"type": "protein", "chain_ids": ["A"], "value": tgt},
        {"type": "protein", "chain_ids": ["B"], "value": binder}]})
    cmd = ["boltz-api", "predictions:structure-and-binding", "run", "--workspace-id", WORKSPACE,
           "--input", inp, "--run-dir", run_dir, "--idempotency-key", did, "--progress-format", "jsonl"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return (did, False, "timeout")
    return (did, True, "folded") if os.path.exists(out) else (did, False, f"rc={p.returncode} {p.stderr[-150:]}")


def epitope_contact(did, epi, offset):
    path = cif_path(did)
    if not os.path.exists(path):
        return None
    m = gemmi.read_structure(path)[0]
    chains = {ch.name: ch for ch in m}
    A, B = chains.get("A"), chains.get("B")
    if A is None or B is None:
        return None
    bpts = [a.pos for r in B for a in r if not a.element.is_hydrogen]
    contacted = []
    for i, res in enumerate(A, start=1):
        full = i + offset
        if any(min((a.pos.dist(p) for p in bpts), default=1e9) <= CONTACT_A for a in res if not a.element.is_hydrogen):
            contacted.append(full)
    n = len(contacted); on = [r for r in contacted if r in epi]
    return {"design_id": did, "epitope_contact": (len(on) / n) if n else 0.0,
            "epitope_coverage": len(on) / len(epi) if epi else 0.0, "n_contact": n, "n_on_epitope": len(on)}


def main():
    if os.path.exists(DONE):
        os.remove(DONE)
    os.makedirs(CACHE, exist_ok=True)
    tgt, offset = target_seq_and_offset()
    epi = epitope_set()
    rows = [r for r in csv.DictReader(open(os.path.join(REPO, "data/processed/labeled_features_bio.csv")))
            if r["target"].upper() == TARGET]
    seen, uniq = set(), []
    for r in rows:
        seq = r["sequence"].strip()
        did = synth_design_id(TARGET, seq)
        if did not in seen and seq:
            seen.add(did); uniq.append((did, seq, r["binds"].strip().lower() == "true"))
    if MAX_DESIGNS and len(uniq) > MAX_DESIGNS:
        # balanced deterministic sample: half binders, half non-binders
        pos = sorted([u for u in uniq if u[2]], key=lambda u: u[0])
        neg = sorted([u for u in uniq if not u[2]], key=lambda u: u[0])
        h = MAX_DESIGNS // 2
        uniq = pos[:h] + neg[:MAX_DESIGNS - h]
    uniq = [(d, s) for d, s, _ in uniq]
    print(f"{TARGET}: {len(rows)} rows -> folding {len(uniq)} (MAX_DESIGNS={MAX_DESIGNS}). construct {len(tgt)}aa offset {offset}, {len(epi)} epitope res", flush=True)
    done, fails = 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fold_one, did, tgt, seq): did for did, seq in uniq}
        for fu in as_completed(futs):
            did, ok, msg = fu.result(); done += 1
            if not ok:
                fails.append((did, msg))
            if done % 10 == 0 or not ok:
                print(f"[{done}/{len(uniq)}] {did} {'OK' if ok else 'FAIL '+msg}", flush=True)
    res = [x for x in (epitope_contact(did, epi, offset) for did, _ in uniq) if x]
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["design_id", "epitope_contact", "epitope_coverage", "n_contact", "n_on_epitope"])
        w.writeheader(); w.writerows(res)
    print(f"\nFolded {len(res)}/{len(uniq)}; {len(fails)} fails. Wrote {OUT_CSV}", flush=True)
    open(DONE, "w").write(json.dumps({"folded": len(res), "total": len(uniq), "fails": len(fails)}))


if __name__ == "__main__":
    main()
