"""A size-fair site metric, and the ceiling the 3-12 residue footprint imposes.

The existing metrics are both one-sided and both gameable by patch size:

  purity   = |patch & epitope| / |patch|    (precision) -- favours SMALL patches
  coverage = |patch & epitope| / |epitope|  (recall)    -- favours LARGE patches

"majority-hit" thresholds purity, so shrinking proposals inflates it. "half-epitope
recovery" thresholds coverage, so it is unreachable when the footprint is smaller
than the epitope -- which is the case here by the tool's own design: patches are
capped at 12 residues because that is a minibinder interface, while the benchmark's
labels are ANTIBODY epitopes with a median of ~18-20 residues.

F1 and Jaccard over (patch, epitope) are symmetric and not gameable by footprint.
Both are computable from the cached purity/coverage arrays at zero extra cost.

Reported per arm: cluster-macro mean of the BEST F1 among the top-k proposals,
against the random control and against the all-patches oracle. The oracle is the
number that matters most here: it is the best F1 any enumerated patch could
achieve, i.e. the hard ceiling the footprint imposes regardless of ranking.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import collections, json, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(DATA / 'deps'))
import train_models as T
from xgboost import XGBClassifier, XGBRegressor, XGBRanker

KS = (1, 3, 5, 10)
REPS = 400
SEED = 20261011


def f1_jacc(r):
    p, c = np.asarray(r['purity'], float), np.asarray(r['coverage'], float)
    with np.errstate(divide='ignore', invalid='ignore'):
        f1 = np.where(p + c > 0, 2 * p * c / (p + c), 0.0)
        inter_over_union = np.where(p + c - p * c > 0, (p * c) / (p + c - p * c), 0.0)
    return np.nan_to_num(f1), np.nan_to_num(inter_over_union)


def best_at_k(rows, preds, score_arrays):
    """cluster-macro mean of max(score) over the top-k ranked proposals."""
    byc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, s in zip(rows, preds):
        order = T.nms(r, np.asarray(s))
        arr = score_arrays[r['id']]
        for k in KS:
            byc[r['cluster']][k].append(float(np.max(arr[order[:k]])) if order else 0.0)
    return {k: float(np.mean([np.mean(byc[c][k]) for c in byc])) for k in KS}


def main():
    rows = T.load()
    test = rows['test']
    F1 = {r['id']: f1_jacc(r)[0] for r in test}
    JA = {r['id']: f1_jacc(r)[1] for r in test}

    old = json.loads((REPO / 'data/eval/prince_connected.json').read_text())
    w = np.array([old['weights'][f] for f in ['exposure', 'concavity', 'hydrophobicity', 'connectivity']])

    arms = {'incumbent': T.baseline(test, w),
            'exposure': T.baseline(test, np.array([1., 0, 0, 0]))}
    val = json.loads((DATA / 'validation_results.json').read_text())
    for name in ('patch_ranker_enriched_d5', 'patch_classifier_enriched_d4', 'patch_regressor_enriched_d2'):
        cfg = val[name]['config']
        cls = {'residue': XGBClassifier, 'patch_classifier': XGBClassifier,
               'patch_regressor': XGBRegressor, 'patch_ranker': XGBRanker}[cfg['kind']]
        m = cls(); m.load_model(DATA / 'models' / f'{name}.json')
        arms[name] = T.predictions(m, test, cfg['kind'], cfg['features'])

    out = {'metric': 'cluster-macro mean of best F1 (and Jaccard) between a proposed patch and the true epitope, among top-k',
           'why': ('F1/Jaccard are symmetric in patch size, unlike purity-thresholded majority-hit '
                   '(favours small patches) or coverage-thresholded half-epitope recovery '
                   '(unreachable when the footprint is smaller than the epitope).'),
           'footprint': {'patch_min_residues': 3, 'patch_max_residues': 12,
                         'rationale_in_source': 'a minibinder interface buries ~10-15 target residues',
                         'median_patch_residues': int(np.median([len(ix) for r in test for ix in r['indices']])),
                         'median_epitope_residues': int(np.median([r['y'].sum() for r in test]))},
           'n_test_interfaces': len(test), 'n_test_clusters': len(set(r['cluster'] for r in test)),
           'arms': {}, 'oracle': {}, 'random': {}}

    for name, pred in arms.items():
        out['arms'][name] = {'f1': {str(k): v for k, v in best_at_k(test, pred, F1).items()},
                             'jaccard': {str(k): v for k, v in best_at_k(test, pred, JA).items()}}

    # Oracle: best over ALL enumerated patches -- the hard ceiling of the footprint.
    for label, arr in (('f1', F1), ('jaccard', JA)):
        byc = collections.defaultdict(list)
        for r in test:
            byc[r['cluster']].append(float(np.max(arr[r['id']])))
        out['oracle'][label] = float(np.mean([np.mean(v) for v in byc.values()]))
        out['oracle'][label + '_per_interface_median'] = float(np.median([np.max(arr[r['id']]) for r in test]))

    rng = np.random.default_rng(SEED)
    draws = {label: {k: [] for k in KS} for label in ('f1', 'jaccard')}
    for _ in range(REPS):
        pr = [rng.random(len(r['indices'])) for r in test]
        for label, arr in (('f1', F1), ('jaccard', JA)):
            m = best_at_k(test, pr, arr)
            for k in KS:
                draws[label][k].append(m[k])
    for label in draws:
        out['random'][label] = {str(k): {'mean': float(np.mean(draws[label][k])),
                                         'sd': float(np.std(draws[label][k]))} for k in KS}
    for name in out['arms']:
        for label in ('f1', 'jaccard'):
            for k in KS:
                d = np.asarray(draws[label][k]); v = out['arms'][name][label][str(k)]
                out['arms'][name].setdefault(label + '_vs_random', {})[str(k)] = {
                    'z': float((v - d.mean()) / d.std()), 'p_random_ge': float((d >= v).mean())}

    T.write(DATA / 'metric_f1.json', out)

    fp = out['footprint']
    print(f"footprint: patches {fp['patch_min_residues']}-{fp['patch_max_residues']} res "
          f"(median {fp['median_patch_residues']}), epitopes median {fp['median_epitope_residues']} res")
    print(f"test: {out['n_test_interfaces']} interfaces, {out['n_test_clusters']} clusters\n")
    print(f"{'arm':32s}" + ''.join(f"{'F1@'+str(k):>16s}" for k in KS))
    for name in out['arms']:
        a = out['arms'][name]
        print(f'{name:32s}' + ''.join(f"{a['f1'][str(k)]:>9.3f} z{a['f1_vs_random'][str(k)]['z']:+5.1f}" for k in KS))
    r = out['random']['f1']
    print(f"{'RANDOM control':32s}" + ''.join(f"{r[str(k)]['mean']:>9.3f}+-{r[str(k)]['sd']:<5.3f}" for k in KS))
    print(f"\nORACLE best-F1 over ALL enumerated patches: {out['oracle']['f1']:.3f} "
          f"(per-interface median {out['oracle']['f1_per_interface_median']:.3f})")
    print(f"ORACLE best-Jaccard: {out['oracle']['jaccard']:.3f}")
    print("\nThe oracle is the ceiling imposed by the 3-12 residue footprint, independent of")
    print("ranking. If it is far below 1.0, the footprint -- not the model -- is the limiter,")
    print("and the antibody-epitope labels are the wrong target for a minibinder-scale tool.")


if __name__ == '__main__':
    main()
