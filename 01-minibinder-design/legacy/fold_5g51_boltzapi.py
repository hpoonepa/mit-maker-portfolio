#!/usr/bin/env python3
"""Fold all 5G51 (DWV VP3 P-domain) minibinder+target complexes via the Boltz API.

Uses the CREDITED boltz-api account (BOLTZ_API_KEY from binder-scorer/.env,
workspace ws_8pN1jAvRejXlTTrXILXm) — free credits, NOT Modal / user's money.
Resume-safe: a design whose CIF already exists is skipped. Idempotency-key per
design prevents duplicate server-side jobs on retry.

Target = 5G51 chain A (RCSB), 155 aa P-domain. Binders read from
VP3_5MV5_all_minibinders.fasta (415 designs).

    MAX_DESIGNS=1 python3 fold_5g51_boltzapi.py     # smoke-test one fold
    python3 fold_5g51_boltzapi.py                   # full 415 (run detached)"""
from __future__ import annotations
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
BINDER_SCORER = os.path.join(os.path.dirname(HERE), "mosaic", "papercrane", "binder-scorer")

# --- credited account key (free credits) -----------------------------------
if not os.environ.get("BOLTZ_API_KEY"):
    envp = os.path.join(BINDER_SCORER, ".env")
    for line in open(envp):
        if line.startswith("BOLTZ_API_KEY="):
            os.environ["BOLTZ_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
WORKSPACE = "ws_8pN1jAvRejXlTTrXILXm"

# 5G51 chain A — DWV VP3 P-domain (from https://www.rcsb.org/fasta/entry/5G51)
TARGET_SEQ = ("EEYRAKTGYAPYYAGVWHSFNNSNSLVFRWGSASDQIAQWPTISVPRGELAFLRIKDGKQAAVGTQPWRTMV"
              "VWPSGHGYNIGIPTYNAERARQLAQHLYGGGSLTDEKAKQLFVPANQQGPGKVSNGNPVWEVMRAPLATQRA"
              "HIQDFEFIEAIPE")

FASTA = os.path.join(HERE, "VP3_5MV5_all_minibinders.fasta")
CACHE = "/tmp/5g51_minibinders_folds"
MARKER = os.path.join(HERE, ".5g51_minibinders_fold.DONE")
WORKERS = int(os.environ.get("FOLD_WORKERS", "6"))
MAX_DESIGNS = int(os.environ["MAX_DESIGNS"]) if os.environ.get("MAX_DESIGNS") else None


def read_binders():
    name, seq, out = None, [], []
    for ln in open(FASTA):
        ln = ln.rstrip("\n")
        if ln.startswith(">"):
            if name and seq:
                out.append((name, "".join(seq)))
            name = re.split(r"\s", ln[1:])[0]
            seq = []
        elif ln:
            seq.append(ln.strip())
    if name and seq:
        out.append((name, "".join(seq)))
    return out


def cif_path(name):
    return os.path.join(CACHE, name, "outputs/files/prediction/sample_0_predicted_structure.cif")


def fold_one(name, binder):
    if os.path.exists(cif_path(name)):
        return (name, True, "cached")
    run_dir = os.path.join(CACHE, name)
    inp = json.dumps({"entities": [
        {"type": "protein", "chain_ids": ["A"], "value": TARGET_SEQ},
        {"type": "protein", "chain_ids": ["B"], "value": binder}]})
    cmd = ["boltz-api", "predictions:structure-and-binding", "run",
           "--workspace-id", WORKSPACE, "--input", inp, "--run-dir", run_dir,
           "--idempotency-key", f"5g51_{name}", "--progress-format", "jsonl"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired:
        return (name, False, "timeout")
    if os.path.exists(cif_path(name)):
        return (name, True, "folded")
    return (name, False, f"rc={p.returncode} {p.stderr[-200:]}")


def main():
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(MARKER):
        os.remove(MARKER)
    binders = read_binders()
    if MAX_DESIGNS:
        binders = binders[:MAX_DESIGNS]
    print(f"5G51: folding {len(binders)} binders vs {len(TARGET_SEQ)}aa target "
          f"(WORKERS={WORKERS}, credited account, free credits)", flush=True)
    done, ok, fails = 0, 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fold_one, n, s): n for n, s in binders}
        for fu in as_completed(futs):
            name, good, msg = fu.result(); done += 1
            if good:
                ok += 1
            else:
                fails.append((name, msg))
            if done % 10 == 0 or not good:
                print(f"[{done}/{len(binders)}] {name} {'OK' if good else 'FAIL ' + msg}", flush=True)
    summary = {"total": len(binders), "folded": ok, "fails": len(fails),
               "fail_names": [f[0] for f in fails]}
    open(MARKER, "w").write(json.dumps(summary, indent=1))
    print(f"\nDONE: folded {ok}/{len(binders)}, {len(fails)} fails. Marker: {MARKER}", flush=True)
    if fails:
        print("Fails:", fails[:10], flush=True)


if __name__ == "__main__":
    main()
