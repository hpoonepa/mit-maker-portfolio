"""Raw recovery counts for the writeup: how many epitopes does the locked model actually find.

Cluster-macro percentages are the statistically correct endpoint but are not what a reader
wants in a sentence. This reports plain interface counts ("X of 110") alongside them, for
the 110 benchmark interfaces and for the full 1,120-interface test split.
Saves the refit model so this never has to be refitted again.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import collections, gzip, json, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sweep as S

CACHE = (DATA / "cache_all")
OUT = (DATA / "recovery"); OUT.mkdir(parents=True, exist_ok=True)
KS = (1, 3, 5, 10)


def main():
    bp = set()
    with gzip.open((REPO / "data/eval/bepipred_connected/residue_predictions.jsonl.gz"), 'rt') as f:
        for line in f:
            bp.add(json.loads(line)['id'])
    print(f'benchmark-110 instance ids: {len(bp)}', flush=True)

    lock = json.loads((DATA / 'sweep_lock.json').read_text())
    cfg = lock['config']; combo = tuple(cfg['combo'])
    index = S.load_index(CACHE)
    train = [r for r in index if r['split'] == 'train' and S.patch_matrix(r['context'], ('geom',)) is not None]
    test = [r for r in index if r['split'] == 'test' and S.patch_matrix(r['context'], ('geom',)) is not None]
    print(f'refit on {len(train)} train; scoring {len(test)} test interfaces', flush=True)
    model = S.fit(S.build_training(train, combo, np.random.default_rng(S.SEED), cfg['kind']), cfg)
    model.save_model(OUT / f"{lock['winner']}__refit_train.json")
    print('refit done and saved', flush=True)

    used, preds = S.predict(model, test, combo, cfg['kind'])
    per = {}
    for r, s in zip(used, preds):
        order = S.nms(r['conflict'], s)
        maj = r['purity'] > .5
        half = r['coverage'] >= .5
        per[r['id']] = {
            'cluster': r['cluster'],
            'majority': {k: bool(np.any(maj[order[:k]])) for k in KS},
            'half': {k: bool(np.any(half[order[:k]])) for k in KS},
            'best_f1': {k: float(np.max(r['f1'][order[:k]])) for k in KS},
            'best_cov': {k: float(np.max(r['coverage'][order[:k]])) for k in KS},
            'oracle_majority': bool(np.any(maj)),
            'oracle_f1': float(np.max(r['f1'])),
        }

    def block(ids, label):
        ids = [i for i in ids if i in per]
        n = len(ids)
        out = {'label': label, 'n_interfaces': n,
               'n_clusters': len(set(per[i]['cluster'] for i in ids))}
        for name, key in (('majority_hit', 'majority'), ('half_epitope', 'half')):
            out[name] = {str(k): {'count': sum(per[i][key][k] for i in ids),
                                  'of': n,
                                  'pct': round(100 * sum(per[i][key][k] for i in ids) / n, 1)}
                         for k in KS}
        out['mean_best_f1'] = {str(k): round(float(np.mean([per[i]['best_f1'][k] for i in ids])), 4) for k in KS}
        out['mean_epitope_coverage'] = {str(k): round(float(np.mean([per[i]['best_cov'][k] for i in ids])), 4) for k in KS}
        out['oracle_majority_count'] = sum(per[i]['oracle_majority'] for i in ids)
        out['oracle_mean_f1'] = round(float(np.mean([per[i]['oracle_f1'] for i in ids])), 4)
        return out

    res = {'locked_model': lock['winner'],
           'benchmark_110': block(bp, 'the 110 published benchmark interfaces'),
           'full_test': block(list(per), 'full held-out test split')}
    (OUT / 'recovery_counts.json').write_text(json.dumps(res, indent=2))

    for b in (res['benchmark_110'], res['full_test']):
        print(f"\n=== {b['label']}: {b['n_interfaces']} interfaces, {b['n_clusters']} clusters ===")
        print(f"{'k':>4}{'majority-hit':>22}{'half-epitope':>22}{'mean best-F1':>14}{'mean epi coverage':>19}")
        for k in KS:
            m, h = b['majority_hit'][str(k)], b['half_epitope'][str(k)]
            print(f"{k:>4}{m['count']:>10}/{m['of']} ({m['pct']:>4.1f}%){h['count']:>10}/{h['of']} ({h['pct']:>4.1f}%)"
                  f"{b['mean_best_f1'][str(k)]:>14.3f}{b['mean_epitope_coverage'][str(k)]:>19.3f}")
        print(f"  oracle majority-hit: {b['oracle_majority_count']}/{b['n_interfaces']}, "
              f"oracle mean best-F1 {b['oracle_mean_f1']:.3f}")
    print(f"\nwrote {OUT/'recovery_counts.json'}")


if __name__ == '__main__':
    main()
