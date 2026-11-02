"""Re-analysis of the SAME validation table under a top-3 primary endpoint.

Why this is a separate script: `selection_lock.json` was pre-registered with
majority-hit@1 as the primary endpoint, and its test result has already been
read. Re-ranking the same validation table by @3 is therefore an EXPLORATORY
re-analysis, not a fresh pre-registration, and it carries a multiplicity cost
that must be disclosed. It retrains nothing and does not touch the original lock.

The rigorous top-3 number comes later, from a fresh pre-registered sweep over
the new feature blocks (see PROTOCOL.md amendment 2).
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
PRIMARY = 3
RANDOM_REPS = 400
RANDOM_SEED = 20261011


def random_control(rows, reps=RANDOM_REPS, seed=RANDOM_SEED):
    rng = np.random.default_rng(seed)
    lab = {r['id']: {'majority_hit': r['purity'] > .5,
                     'half_epitope_recovery': r['coverage'] >= .5} for r in rows}
    dist = {m: {k: [] for k in KS} for m in ('majority_hit', 'half_epitope_recovery')}
    for _ in range(reps):
        byc = {m: collections.defaultdict(lambda: collections.defaultdict(list)) for m in dist}
        for r in rows:
            order = T.nms(r, rng.random(len(r['indices'])))
            for m in dist:
                for k in KS:
                    byc[m][r['cluster']][k].append(bool(np.any(lab[r['id']][m][order[:k]])))
        for m in dist:
            for k in KS:
                dist[m][k].append(float(np.mean([np.mean(byc[m][c][k]) for c in byc[m]])))
    return dist


def vs_random(value, draws):
    d = np.asarray(draws)
    return {'component_macro': float(value),
            'z_vs_random': float((value - d.mean()) / d.std()),
            'p_random_ge_arm': float((d >= value).mean())}


def main():
    val = json.loads((DATA / 'validation_results.json').read_text())
    orig_lock = json.loads((DATA / 'selection_lock.json').read_text())
    if orig_lock['validation_sha256'] != T.digest(DATA / 'validation_results.json'):
        raise ValueError('validation table changed since the original lock; refusing to re-analyse')

    def key(name):
        s = val[name]['summary']['majority_hit']
        return tuple(s[str(k)]['component_macro'] for k in (PRIMARY, 1, 5, 10))

    ranking = sorted(val, key=key, reverse=True)
    winner = ranking[0]
    rows = T.load()

    lock = {
        'winner': winner,
        'config': val[winner].get('config'),
        'criterion': f'validation component-macro majority-hit@{PRIMARY}, tiebreak @1 then @5 then @10',
        'status': 'EXPLORATORY re-analysis of a pre-computed validation table',
        'disclosure': ('The original pre-registration used majority-hit@1 as primary and its test '
                       'result was already read before this re-ranking. This @3 result is therefore '
                       'not pre-registered and carries an undisclosed-multiplicity risk. Treat as '
                       'hypothesis-generating only.'),
        'original_lock_winner': orig_lock['winner'],
        'validation_ranking_by_at3': [
            {'name': n, 'at3': val[n]['summary']['majority_hit']['3']['component_macro']} for n in ranking],
        'validation_sha256': T.digest(DATA / 'validation_results.json'),
        'script_sha256': T.digest(__file__),
    }
    T.write(DATA / 'selection_lock_top3.json', lock)
    print('WINNER@3:', winner, json.dumps(lock['validation_ranking_by_at3'][:4]), flush=True)

    old = json.loads((REPO / 'data/eval/prince_connected.json').read_text())
    w = np.array([old['weights'][f] for f in ['exposure', 'concavity', 'hydrophobicity', 'connectivity']])
    cfg = val[winner].get('config')
    if cfg:
        cls = {'residue': XGBClassifier, 'patch_classifier': XGBClassifier,
               'patch_regressor': XGBRegressor, 'patch_ranker': XGBRanker}[cfg['kind']]
        model = cls()
        model.load_model(DATA / 'models' / f'{winner}.json')
        pred = T.predictions(model, rows['test'], cfg['kind'], cfg['features'])
    else:
        pred = T.baseline(rows['test'], w if winner == 'incumbent' else np.array([1, 0, 0, 0]))

    prev = json.loads((DATA / 'test_results.json').read_text())
    out = {'status': 'EXPLORATORY top-3 re-analysis', 'lock': lock,
           'incumbent': T.metrics(rows['test'], T.baseline(rows['test'], w)),
           'exposure': T.metrics(rows['test'], T.baseline(rows['test'], np.array([1, 0, 0, 0]))),
           'selected_at3': T.metrics(rows['test'], pred),
           'selected_at1_from_original_lock': prev['selected']}
    out['paired_at3_minus_incumbent'] = T.paired(out['selected_at3'], out['incumbent'])
    out['paired_at3_minus_exposure'] = T.paired(out['selected_at3'], out['exposure'])

    dist = random_control(rows['test'])
    out['random_control'] = {m: {str(k): {'mean': float(np.mean(dist[m][k])), 'sd': float(np.std(dist[m][k]))}
                                 for k in KS} for m in dist}
    out['vs_random'] = {}
    for arm in ('incumbent', 'exposure', 'selected_at3', 'selected_at1_from_original_lock'):
        out['vs_random'][arm] = {m: {str(k): vs_random(out[arm]['summary'][m][str(k)]['component_macro'], dist[m][k])
                                     for k in KS} for m in dist}
    T.write(DATA / 'test_results_top3.json', out)

    print(f"\n{'arm':34s}" + ''.join(f"{'@'+str(k):>16s}" for k in KS))
    for arm in ('incumbent', 'exposure', 'selected_at1_from_original_lock', 'selected_at3'):
        s = out[arm]['summary']['majority_hit']
        v = out['vs_random'][arm]['majority_hit']
        print(f'{arm:34s}' + ''.join(
            f"{s[str(k)]['hits']:>4d}/110 z{v[str(k)]['z_vs_random']:+4.1f} " for k in KS))
    r = out['random_control']['majority_hit']
    print(f"{'RANDOM control':34s}" + ''.join(f"{r[str(k)]['mean']:>9.3f}+-{r[str(k)]['sd']:<5.3f}" for k in KS))
    print(f"\nPRIMARY @3 p(random>=arm): selected_at3={out['vs_random']['selected_at3']['majority_hit']['3']['p_random_ge_arm']:.4f}"
          f"  incumbent={out['vs_random']['incumbent']['majority_hit']['3']['p_random_ge_arm']:.4f}")
    d = out['paired_at3_minus_incumbent']['majority_hit']['3']
    print(f"paired @3 selected-incumbent: {d['component_difference']:+.3f} CI [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]")


if __name__ == '__main__':
    main()
