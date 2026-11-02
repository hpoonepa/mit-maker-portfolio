"""Does more data help, or are the 51 geometric features the ceiling?

Uses the TRAIN split only, with grouped CV over antigen clusters. The val and test
splits are never touched, so this is safe to run and read freely.

If the curve is still climbing at 100% of the 116 train clusters, the full-manifest
scale-up (~1,160 train clusters) is the right investment. If it is flat, more data
will not help and the feature representation is the binding constraint.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import collections, json, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(DATA / 'deps'))
import train_models as T
from sklearn.model_selection import GroupKFold

FRACTIONS = (0.125, 0.25, 0.5, 1.0)
FOLDS = 5
SEED = 17
KS = (1, 3, 5, 10)
PRIMARY = 3


def cluster_macro(rows, preds, metric='majority_hit'):
    byc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, s in zip(rows, preds):
        order = T.nms(r, np.asarray(s))
        lab = r['purity'] > .5 if metric == 'majority_hit' else r['coverage'] >= .5
        for k in KS:
            byc[r['cluster']][k].append(bool(np.any(lab[order[:k]])))
    return {k: float(np.mean([np.mean(byc[c][k]) for c in byc])) for k in KS}


def random_macro(rows, reps=200, seed=SEED):
    rng = np.random.default_rng(seed)
    out = {k: [] for k in KS}
    for _ in range(reps):
        byc = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in rows:
            order = T.nms(r, rng.random(len(r['indices'])))
            lab = r['purity'] > .5
            for k in KS:
                byc[r['cluster']][k].append(bool(np.any(lab[order[:k]])))
        for k in KS:
            out[k].append(float(np.mean([np.mean(byc[c][k]) for c in byc])))
    return {k: (float(np.mean(out[k])), float(np.std(out[k]))) for k in KS}


def main():
    rows = T.load()['train']
    groups = np.array([r['cluster'] for r in rows])
    n_clusters = len(set(groups))
    print(f'train: {len(rows)} interfaces, {n_clusters} clusters', flush=True)

    configs = [
        {'kind': 'patch_classifier', 'features': 'enriched', 'depth': 4},
        {'kind': 'patch_regressor', 'features': 'enriched', 'depth': 4},
        {'kind': 'residue', 'features': 'enriched', 'depth': 4},
    ]
    gkf = GroupKFold(n_splits=FOLDS)
    splits = list(gkf.split(np.arange(len(rows)), groups=groups))
    rng = np.random.default_rng(SEED)
    results = {'train_interfaces': len(rows), 'train_clusters': n_clusters,
               'folds': FOLDS, 'fractions': list(FRACTIONS), 'seed': SEED,
               'primary_endpoint': f'cluster-macro majority-hit@{PRIMARY}',
               'note': 'TRAIN split only, grouped CV by antigen cluster; val/test untouched.',
               'curves': {}, 'random_control_per_fold': []}

    for fi, (tr_idx, te_idx) in enumerate(splits):
        held = [rows[i] for i in te_idx]
        results['random_control_per_fold'].append(
            {str(k): v for k, v in random_macro(held, reps=120, seed=SEED + fi).items()})

    for cfg in configs:
        name = f"{cfg['kind']}_d{cfg['depth']}"
        results['curves'][name] = {}
        for frac in FRACTIONS:
            scores = {k: [] for k in KS}
            for fi, (tr_idx, te_idx) in enumerate(splits):
                tr_clusters = sorted(set(groups[tr_idx]))
                n_keep = max(2, int(round(frac * len(tr_clusters))))
                keep = set(rng.permutation(tr_clusters)[:n_keep].tolist())
                sub = [rows[i] for i in tr_idx if groups[i] in keep]
                held = [rows[i] for i in te_idx]
                model = T.train(sub, cfg)
                pred = T.predictions(model, held, cfg['kind'], cfg['features'])
                m = cluster_macro(held, pred)
                for k in KS:
                    scores[k].append(m[k])
            results['curves'][name][str(frac)] = {
                'clusters_used_mean': float(np.mean([max(2, int(round(frac * len(set(groups[tr])))))
                                                     for tr, _ in splits])),
                **{str(k): {'mean': float(np.mean(scores[k])), 'sd': float(np.std(scores[k]))} for k in KS}}
            p = results['curves'][name][str(frac)][str(PRIMARY)]
            print(f"  {name:26s} frac={frac:<6} @{PRIMARY} {p['mean']:.3f} +/- {p['sd']:.3f}", flush=True)

    rc = np.mean([f[str(PRIMARY)][0] for f in results['random_control_per_fold']])
    results['random_control_at_primary'] = float(rc)
    T.write(DATA / 'learning_curve.json', results)

    print(f"\n=== cluster-macro majority-hit@{PRIMARY} vs fraction of train clusters ===")
    print(f"{'model':26s}" + ''.join(f"{str(int(f*100))+'%':>14s}" for f in FRACTIONS) + '     slope(last half)')
    for name, cur in results['curves'].items():
        vals = [cur[str(f)][str(PRIMARY)]['mean'] for f in FRACTIONS]
        sds = [cur[str(f)][str(PRIMARY)]['sd'] for f in FRACTIONS]
        slope = vals[-1] - vals[-2]
        print(f'{name:26s}' + ''.join(f'{v:>7.3f}+-{s:<5.3f}' for v, s in zip(vals, sds)) + f'   {slope:+.3f}')
    print(f"{'RANDOM control':26s}{rc:>7.3f}")
    print("\nInterpretation: a positive slope from 50%->100% means the curve is still")
    print("climbing and the full-manifest scale-up (~10x train clusters) should pay off.")


if __name__ == '__main__':
    main()
