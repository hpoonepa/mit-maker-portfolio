"""How easy is the 'top-k touches the epitope' metric?

For every test antigen: enumerate the candidate patch pool the ranker ranks, and
measure what fraction of the WHOLE POOL touches the epitope. That fraction IS the
random baseline's expected per-draw hit rate. If it is high, the metric is near
saturated and no ranker can look good against random on it.

Writes one JSON record per antigen with every patch's overlap with the epitope,
so harder metrics can be asked of the same pool without re-enumerating.
"""
import json, sys, time
from pathlib import Path
sys.path[:0] = ["src", "."]
from benchmark.evaluate import load_manifest
from benchmark.structures import load_antigen
from hotspot_preflight.checks.burial import compute_burial, reference_max_sasa
from hotspot_preflight.surface import enumerate_patches
from hotspot_preflight.predict.geometric import GeometricPredictor
from hotspot_preflight.predict.profiles import (
    EXPOSURE_ONLY, ANTIBODY_EPITOPE, DESIGNABILITY,
)

SPLIT, OUT, LIMIT = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
CACHE = Path(".cache/benchmark/cif").resolve()

insts, _ = load_manifest(Path("data/benchmark/manifest.csv"), split=SPLIT)

done = set()
if OUT.exists():
    for line in OUT.open():
        try: done.add(json.loads(line)["id"])
        except Exception: pass

ARMS = {
    "exposure": GeometricPredictor(name="exposure", profile=EXPOSURE_ONLY),
    "fitted":   GeometricPredictor(name="fitted",   profile=ANTIBODY_EPITOPE),
    "shipped":  GeometricPredictor(name="shipped",  profile=DESIGNABILITY),
}

t0 = time.time(); n = 0
with OUT.open("a") as fh:
    for inst in insts:
        if n >= LIMIT: break
        if inst.instance_id in done: n += 1; continue
        n += 1
        try:
            target, used_assembly = load_antigen(CACHE, inst.pdb_id, inst.antigen_chains)
            maxima, prov = reference_max_sasa(target.st)
            profile = compute_burial(
                target.st, "assembly" if used_assembly else "chain",
                reference=(maxima, prov),
            )
            patches = enumerate_patches(target, profile)
            if not patches:
                fh.write(json.dumps({"id": inst.instance_id, "err": "no_patches"}) + "\n"); fh.flush()
                continue
            ep = set(inst.epitope_residues)

            # The pool, in each arm's ranked order. rank() applies NMS, so the
            # surviving set is what a top-k window actually draws from.
            out = {"id": inst.instance_id, "cluster": inst.cluster_id,
                   "n_epitope": len(ep), "n_enumerated": len(patches)}
            for arm_name, arm in ARMS.items():
                ranked = arm.rank(target, profile, patches)
                rows = []
                for sp in ranked:
                    members = [str(k) for k in sp.patch.residues]
                    inter = len(ep.intersection(members))
                    rows.append([len(members), inter])
                out[arm_name] = rows
            fh.write(json.dumps(out) + "\n"); fh.flush()
        except Exception as e:
            fh.write(json.dumps({"id": inst.instance_id,
                                 "err": f"{type(e).__name__}: {e}"[:160]}) + "\n")
            fh.flush()
        if n % 20 == 0:
            print(f"{n}/{LIMIT}  {time.time()-t0:.0f}s", flush=True)
print(f"done n={n} {time.time()-t0:.0f}s", flush=True)
