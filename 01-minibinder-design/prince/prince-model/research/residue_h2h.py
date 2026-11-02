"""Residue-level AUROC head-to-head: PRINCE v2 (CV-locked) vs BepiPred-3.0 vs PeSTo.

The locked v2 result is PATCH-level (majority-hit@3); BepiPred and PeSTo emit PER-RESIDUE
scores. This projects the locked patch model down to residues and scores all three on the
identical residue universe, labels and aggregation used in the shipped comparison:
within-instance AUROC, mean within cluster, mean across clusters.

Everything is joined BY RESIDUE KEY, never by position: BepiPred's residue order agrees
with the cache key order for only 105/110 interfaces, so a positional read would scramble
five of them. PeSTo is likewise keyed (its preprocessing renumbers and drops insertion
codes, so a positional read there misassigns ~10% of keys).

Projection: residue score = max score among enumerated patches containing it. Residues in
no patch were never proposable, so they rank below every patch-covered residue. That floor
hands us "buried residues are not epitopes" for free, which is not ranking skill, so the
same AUROC restricted to patch-covered residues -- with all arms restricted identically --
is reported as the honest arm.

Leakage: all 110 comparison interfaces sit in the v2 TEST split, so the refit never sees
them. Instance-level BepiPred/PeSTo leak flags come from the contamination audit, joined
on (BepiPred score vector, label vector, PeSTo score vector), which is unique for all 110.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import collections, gzip, json, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sweep as S
from sklearn.metrics import roc_auc_score

ROOT = REPO
CACHE = (DATA / "cache_all")
PESTO = (DATA / "pesto_cache")
OUT = (DATA / "h2h")
BOOT, SEED = 2000, 20261011
AUTHOR_KEY = lambda a: f'{a[0]}:{a[1]}:{a[2]}'


def auroc(y, s):
    y = np.asarray(y, bool)
    if y.all() or not y.any() or len(y) < 2:
        return None
    s = np.asarray(s, float)
    if not np.isfinite(s).all():
        return None
    return float(roc_auc_score(y, s))


def macro(per, cluster_of, ids):
    byc = collections.defaultdict(list)
    for i in ids:
        if per.get(i) is not None:
            byc[cluster_of[i]].append(per[i])
    if not byc:
        return None, 0, 0
    return (float(np.mean([np.mean(v) for v in byc.values()])),
            sum(len(v) for v in byc.values()), len(byc))


def main():
    # ---------------- BepiPred, keyed per instance
    bp = {}
    with gzip.open(ROOT / 'data/eval/bepipred_connected/'
                          'residue_predictions.jsonl.gz', 'rt') as f:
        for line in f:
            d = json.loads(line)
            bp[d['id']] = {'score': {AUTHOR_KEY(r['author']): float(r['score']) for r in d['residues']},
                           'label': {AUTHOR_KEY(r['author']): int(r['label']) for r in d['residues']},
                           'cluster': d['cluster']}
    print(f'BepiPred instances: {len(bp)}', flush=True)

    leak = json.loads((OUT / 'leakflags.json').read_text())
    print(f'instance-level leak flags: {len(leak)}', flush=True)

    # ---------------- locate each instance in cache_all
    meta = {}
    for f in sorted(CACHE.glob('*.json.gz')):
        with gzip.open(f, 'rt') as s:
            ctx = json.load(s)
        hit = [i for i in ctx['instances'] if i['id'] in bp]
        if not hit or not ctx['patches']:
            continue
        keys, disp = list(ctx['keys']), list(ctx['display_keys'])
        for inst in hit:
            pos = set(inst['epitope'])
            y = np.fromiter((d in pos for d in disp), bool, len(disp))
            if y.sum() != len(pos):
                raise ValueError(f'label identity lost for {inst["id"]}')
            # independent check: our labels must equal BepiPred's own label column
            bl = np.asarray([bp[inst['id']]['label'].get(k, -1) for k in keys])
            if not np.array_equal(bl, y.astype(int)):
                raise ValueError(f'label mismatch vs BepiPred source for {inst["id"]}')
            meta[inst['id']] = {'context': ctx['context_id'], 'keys': keys, 'split': inst['split'],
                                'cluster': inst['cluster'], 'y': y,
                                'patches': [np.asarray(p['indices'], int) for p in ctx['patches']]}
    print(f'located {len(meta)}/110 in cache_all; labels verified against BepiPred source', flush=True)
    splits = collections.Counter(v['split'] for v in meta.values())
    print(f'splits: {dict(splits)}', flush=True)
    assert set(splits) == {'test'}, 'comparison instances must all be in the v2 test split'

    # ---------------- refit the CV-locked model exactly as phase_test does
    lock = json.loads((DATA / 'sweep_lock.json').read_text())
    cfg = lock['config']; combo = tuple(cfg['combo'])
    print(f"locked: {lock['winner']} combo={combo}", flush=True)
    index = S.load_index(CACHE)
    train = [r for r in index if r['split'] == 'train'
             and S.patch_matrix(r['context'], ('geom',)) is not None]
    print(f'refit on {len(train)} train interfaces '
          f'({len(set(r["cluster"] for r in train))} clusters)', flush=True)
    model = S.fit(S.build_training(train, combo, np.random.default_rng(S.SEED), cfg['kind']), cfg)
    print('refit done', flush=True)

    pscore = {}
    for cid in sorted({v['context'] for v in meta.values()}):
        m = S.patch_matrix(cid, combo)
        if m is not None:
            pscore[cid] = (model.predict_proba(m)[:, 1] if cfg['kind'] == 'patch_classifier'
                           else np.asarray(model.predict(m), float))

    # ---------------- per-instance AUROC, all arms on the identical key set
    per = collections.defaultdict(dict)
    cluster_of, cov_fracs, details = {}, [], {}
    for iid, mv in meta.items():
        keys, y, cid = mv['keys'], mv['y'], mv['context']
        cluster_of[iid] = mv['cluster']
        ps = pscore.get(cid)
        if ps is None or len(ps) != len(mv['patches']):
            continue
        rs = np.full(len(keys), np.nan)
        for p, sc in zip(mv['patches'], ps):
            rs[p] = np.fmax(rs[p], sc)
        cov = ~np.isnan(rs)
        cov_fracs.append(cov.mean())
        v2 = np.where(cov, rs, np.nanmin(rs) - 1.0)
        b = np.asarray([bp[iid]['score'][k] for k in keys], float)
        pfile = PESTO / f'{cid}.json.gz'
        pv = None
        if pfile.exists():
            pd_ = json.loads(gzip.open(pfile, 'rt').read())
            m = dict(zip(pd_['keys'], pd_['pesto_ppi']))
            vals = [m.get(k) for k in keys]
            if all(v is not None for v in vals):
                pv = np.asarray(vals, float)
        per['prince_v2'][iid] = auroc(y, v2)
        per['bepipred3'][iid] = auroc(y, b)
        per['pesto'][iid] = auroc(y, pv) if pv is not None else None
        if cov.sum() > 1 and y[cov].any() and not y[cov].all():
            per['prince_v2_covered'][iid] = auroc(y[cov], rs[cov])
            per['bepipred3_covered'][iid] = auroc(y[cov], b[cov])
            per['pesto_covered'][iid] = auroc(y[cov], pv[cov]) if pv is not None else None
        details[iid] = {'cluster': mv['cluster'], 'n_res': len(keys), 'n_pos': int(y.sum()),
                        'patch_covered': float(cov.mean()), **leak.get(iid, {}),
                        'auroc': {k: per[k].get(iid) for k in per}}
    print(f'mean patch-covered fraction: {np.mean(cov_fracs):.3f}', flush=True)

    ids = list(meta)
    subsets = {'all_110': ids,
               'bepipred_clean': [i for i in ids if not leak[i]['bp_leak']],
               'bepipred_clean_strict': [i for i in ids if not leak[i]['bp_leak_pre']],
               'pesto_clean': [i for i in ids if not leak[i]['pesto_leak']],
               'both_clean': [i for i in ids if not leak[i]['bp_leak'] and not leak[i]['pesto_leak']]}

    res = {'locked_model': lock['winner'], 'combo': list(combo),
           'projection': 'residue score = max over enumerated patches containing it; '
                         'uncovered residues floored below all covered ones',
           'aggregation': 'within-instance AUROC, mean within cluster, mean across clusters',
           'join': 'by residue key (BepiPred order matches cache order for only 105/110)',
           'mean_patch_covered_fraction': float(np.mean(cov_fracs)),
           'n_instances': len(meta), 'subsets': {}, 'paired': {}, 'instances': details}
    for sn, sids in subsets.items():
        res['subsets'][sn] = {'n_instances': len(sids), 'arms': {}}
        for arm in per:
            m, n, nc = macro(per[arm], cluster_of, sids)
            res['subsets'][sn]['arms'][arm] = {'macro_auroc': m, 'n_scored': n, 'n_clusters': nc}

    rng = np.random.default_rng(SEED)
    for sn, sids in subsets.items():
        res['paired'][sn] = {}
        for a, b_ in (('prince_v2', 'bepipred3'), ('prince_v2', 'pesto'),
                      ('prince_v2_covered', 'bepipred3_covered'),
                      ('prince_v2_covered', 'pesto_covered')):
            byc = collections.defaultdict(list)
            for i in sids:
                x, z = per[a].get(i), per[b_].get(i)
                if x is not None and z is not None:
                    byc[cluster_of[i]].append((x, z))
            cl = list(byc)
            if len(cl) < 3:
                continue
            f = lambda sel, j: np.mean([np.mean([t[j] for t in byc[c]]) for c in sel])
            obs = float(f(cl, 0) - f(cl, 1))
            d = np.asarray([f([cl[j] for j in rng.choice(len(cl), len(cl), True)], 0) -
                            f([cl[j] for j in rng.choice(len(cl), len(cl), True)], 1)
                            for _ in range(0)]) if False else None
            draws = []
            for _ in range(BOOT):
                sel = [cl[j] for j in rng.choice(len(cl), len(cl), True)]
                draws.append(f(sel, 0) - f(sel, 1))
            d = np.asarray(draws)
            res['paired'][sn][f'{a}_minus_{b_}'] = {
                'delta': obs, 'ci95': [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
                'p_two_sided': float(2 * min((d <= 0).mean(), (d >= 0).mean())),
                'n_clusters': len(cl), 'n_instances': sum(len(v) for v in byc.values())}

    (OUT / 'residue_h2h.json').write_text(json.dumps(res, indent=2, default=float))

    cols = ['all_110', 'bepipred_clean', 'pesto_clean', 'both_clean']
    print('\n=== macro AUROC, ALL residues (shipped comparison universe) ===')
    print(f"{'arm':22s}" + ''.join(f'{c:>22s}' for c in cols))
    for arm in ('prince_v2', 'bepipred3', 'pesto'):
        r = f'{arm:22s}'
        for c in cols:
            a = res['subsets'][c]['arms'][arm]
            r += f"{a['macro_auroc']:>14.4f} (n={a['n_scored']:>3d})" if a['macro_auroc'] else f"{'n/a':>22s}"
        print(r)
    print('\n=== macro AUROC, PATCH-COVERED residues only (all arms restricted alike) ===')
    print(f"{'arm':22s}" + ''.join(f'{c:>22s}' for c in cols))
    for arm in ('prince_v2_covered', 'bepipred3_covered', 'pesto_covered'):
        r = f'{arm:22s}'
        for c in cols:
            a = res['subsets'][c]['arms'].get(arm, {})
            v = a.get('macro_auroc')
            r += f"{v:>14.4f} (n={a['n_scored']:>3d})" if v else f"{'n/a':>22s}"
        print(r)
    print('\n=== paired cluster bootstrap (2000 draws) ===')
    for sn in cols:
        for k, v in res['paired'].get(sn, {}).items():
            print(f"  {sn:22s} {k:42s} {v['delta']:+.4f} "
                  f"[{v['ci95'][0]:+.4f},{v['ci95'][1]:+.4f}] p={v['p_two_sided']:.3f} "
                  f"({v['n_clusters']} clusters)")
    print(f"\nwrote {OUT/'residue_h2h.json'}")


if __name__ == '__main__':
    main()
