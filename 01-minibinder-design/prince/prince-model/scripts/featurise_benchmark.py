"""Per-residue featurisation for the ranker-fix experiment.
Writes JSONL incrementally: one record per instance, raw (unweighted) features
plus the epitope label. Resumable. TRAIN and TEST written to separate files so
the test file is never opened during fitting.
"""
import csv, json, sys, time
from pathlib import Path
sys.path[:0] = ["src", "."]
from benchmark.evaluate import _antibody_chains, load_manifest
from benchmark.manifest import format_residue_key, parse_residues
from benchmark.structures import load_antigen
from hotspot_preflight.checks.burial import compute_burial, reference_max_sasa
from hotspot_preflight.predict.geometric import (
    assembly_context, residue_points, residue_names,
    exposure_feature, concavity_feature, hydrophobicity_feature,
    connectivity_feature, EXPOSED_RELATIVE_SASA,
)

SPLIT, OUT, LIMIT = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
CACHE = Path(".cache/benchmark/cif").resolve()

insts = load_manifest(Path("data/benchmark/manifest.csv"), split=SPLIT)
insts = insts[0] if isinstance(insts, tuple) else insts
with open("data/benchmark/manifest.csv") as manifest_file:
    epitope_keys = {
        f"{row['pdb_id']}:{'+'.join(_antibody_chains(row))}": set(parse_residues(row["epitope_residues"]))
        for row in csv.DictReader(manifest_file)
    }

done = set()
if OUT.exists():
    for line in OUT.open():
        try: done.add(json.loads(line)["id"])
        except Exception: pass

t0 = time.time(); n = 0
with OUT.open("a") as fh:
    for inst in insts:
        if n >= LIMIT: break
        if inst.instance_id in done: n += 1; continue
        try:
            target, used_assembly = load_antigen(CACHE, inst.pdb_id, inst.antigen_chains)
            maxima, prov = reference_max_sasa(target.st)
            profile = compute_burial(target.st, "assembly" if used_assembly else "chain",
                                     reference=(maxima, prov))
            structure = assembly_context(target, profile)
            points, names = residue_points(structure), residue_names(structure)
            surface = [k for k, r in profile.relative_sasa.items() if r >= EXPOSED_RELATIVE_SASA]
            ep = epitope_keys[inst.instance_id]
            rec = {"id": inst.instance_id, "cluster": inst.cluster_id,
                   "residue_encoding": "chain:seq[:icode]", "res": []}
            for key in profile.relative_sasa:
                if key.auth_asym_id not in inst.antigen_chains:
                    continue
                rec["res"].append([
                    format_residue_key(key),
                    round(exposure_feature(key, profile), 5),
                    round(concavity_feature(key, points), 5),
                    round(hydrophobicity_feature(names.get(key, "UNK")), 5),
                    round(connectivity_feature(key, points, surface), 5),
                    1 if key in ep else 0,
                ])
            fh.write(json.dumps(rec) + "\n"); fh.flush(); n += 1
        except Exception as e:
            fh.write(json.dumps({"id": inst.instance_id, "err": f"{type(e).__name__}: {e}"[:150]}) + "\n")
            fh.flush(); n += 1
        if n % 25 == 0: print(f"{SPLIT} {n}/{LIMIT}  {time.time()-t0:.0f}s", flush=True)
print(f"{SPLIT} done n={n}", flush=True)
