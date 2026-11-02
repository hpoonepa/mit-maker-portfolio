#!/usr/bin/env python3
"""Evaluate every cached-feature held-out interface with real structural proposals.

No sampling or patch cap. Reports majority-epitope hit and >=50%-epitope
coverage separately; these answer different questions. No literature labels
are available, so this is a structural-only evaluation, not an evidence ablation.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from benchmark.evaluate import _antibody_chains, load_manifest
from benchmark.geometric_predictor import GeometricArm
from benchmark.preflight_filter import PreflightFilter
from hotspot_preflight.predict.geometric import GeometricPredictor
from hotspot_preflight.predict.profiles import ANTIBODY_EPITOPE, EXPOSURE_ONLY


def one(group):
    """Same coordinates/declared chains share predictions, not epitope labels."""
    instance = group[0]
    try:
        ranked = {}
        for name, profile in (("fitted", ANTIBODY_EPITOPE), ("exposure_only", EXPOSURE_ONLY)):
            arm = GeometricArm(ROOT / '.cache/benchmark/cif', max_patches=None,
                               predictor=GeometricPredictor(profile=profile), cache_size=0)
            prediction = arm(instance)
            filtered = PreflightFilter(ROOT / '.cache/benchmark/cif')(instance, prediction)
            ranked[name] = prediction.ranked_patches
            ranked[name + '+filter'] = [p for p in prediction.ranked_patches
                                       if not set(p).intersection(filtered.killed)]
        outputs = []
        for instance in group:
            epitope = set(instance.epitope_residues)
            output = {"id": instance.instance_id, "cluster": instance.cluster_id, "arms": {}}
            for label, patches in ranked.items():
                output['arms'][label] = {
                    'n_patches': len(patches),
                    'majority_hit': {str(k): any(len(set(p) & epitope) > len(p) / 2 for p in patches[:k]) for k in (1,3,5,10)},
                    'half_epitope_recovery': {str(k): any(len(set(p) & epitope) >= len(epitope) / 2 for p in patches[:k]) for k in (1,3,5,10)},
                }
            output['assembly_stats'] = arm.stats
            outputs.append(output)
        return outputs
    except Exception as exc:
        return [{'id': instance.instance_id, 'cluster': instance.cluster_id,
                 'error': f'{type(exc).__name__}: {exc}'} for instance in group]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation', type=Path, default=ROOT/'data/eval/prince_connected.json')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    model = json.loads(args.evaluation.read_text())
    manifest = args.evaluation.with_suffix('.manifest.csv')
    with manifest.open() as stream:
        rows = list(csv.DictReader(stream))
    requested = set(model['split_ids']['test'])
    canonical = {f"{r['pdb_id']}:{'+'.join(_antibody_chains(r))}" for r in rows if r['instance_id'] in requested}
    instances, dropped = load_manifest(manifest, split='test')
    instances = [i for i in instances if i.instance_id in canonical]
    if len(instances) != len(requested):
        raise ValueError('Held-out instance join lost rows; refusing silent exclusion')
    groups = defaultdict(list)
    for instance in instances:
        groups[(instance.pdb_id, instance.antigen_chains)].append(instance)
    outcomes = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out.with_suffix('.jsonl')
    print(f"Evaluating all {len(instances)} interfaces using {len(groups)} distinct antigen contexts", flush=True)
    with checkpoint.open('w') as stream, ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, group) for group in groups.values()]
        for future in as_completed(futures):
            for result in future.result():
                outcomes.append(result)
                stream.write(json.dumps(result, allow_nan=False) + '\n')
                stream.flush()
                print(f"{len(outcomes)}/{len(instances)} {result['id']} {'ERROR' if 'error' in result else 'ok'}", flush=True)
    outcomes.sort(key=lambda row: row['id'])
    valid = [r for r in outcomes if 'error' not in r]
    summary = {}
    for arm in ('fitted','fitted+filter','exposure_only','exposure_only+filter'):
        summary[arm] = {}
        for metric in ('majority_hit','half_epitope_recovery'):
            summary[arm][metric] = {}
            for k in ('1','3','5','10'):
                clusters = defaultdict(list)
                for row in valid:
                    clusters[row['cluster']].append(int(row['arms'][arm][metric][k]))
                summary[arm][metric][k] = {
                    'hits': sum(row['arms'][arm][metric][k] for row in valid),
                    'n': len(valid),
                    'cluster_macro': float(np.mean([np.mean(v) for v in clusters.values()])) if valid else None,
                }
    result = {'schema_version':1, 'requested_instances':len(instances), 'evaluated_instances':len(valid),
        'errors':[r for r in outcomes if 'error' in r], 'patch_cap':None,
        'candidate_universe': 'Declared original antigen chains; assembly copies supply context only',
        'distinct_antigen_contexts': len(groups),
        'source_sha256': {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (args.evaluation, manifest, ROOT/'data/eval/features_corrected.jsonl.gz',
                         ROOT/'benchmark/geometric_predictor.py', ROOT/'benchmark/preflight_filter.py',
                         ROOT/'src/hotspot_preflight/predict/profiles.py', Path(__file__).resolve())
        },
        'majority_hit_definition': 'Any top-k patch has >50% of its own residues in observed epitope',
        'half_epitope_recovery_definition': 'Any top-k patch covers >=50% of observed epitope residues',
        'filter_policy':'drop entire patch if any constituent residue is killed',
        'evidence_ablation':'NOT RUN: no independent reviewed literature labels',
        'limitation':'Retrospective structural evaluation on 110 cached-feature held-out interfaces, not all 8241; no untouched external holdout.',
        'summary':summary, 'instances':outcomes}
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='instances'},indent=2))


if __name__ == '__main__':
    main()
