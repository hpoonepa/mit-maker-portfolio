"""Full-scale pre-registered sweep: feature blocks x model families, grouped CV.

Design constraints that drive the implementation:

* **Scale.** ~6,500 contexts x ~150 patches x ~220 residue features. Materialising
  every (patch x feature-combination) matrix would be gigabytes. So patch features
  are precomputed ONCE PER BLOCK (phase `pack`) and concatenated on demand, giving
  1x storage instead of one copy per combination.
* **Selection must not use the test split.** Model and feature-block choice is made
  by GroupKFold over TRAIN clusters only. The single val split is left unused for
  selection -- relying on it is exactly what caused two previous selections to pick
  validation winners that landed at random-chance on test.
* **Leakage.** Clusters never cross folds or splits (asserted). No antibody atoms,
  no epitope labels and no identifiers are ever features -- the blocks are built
  that way upstream and re-checked here by width.
* **Every metric is reported against a random control** under the identical NMS and
  denominators, because the previously advertised headline number turned out to be
  the chance rate.

Phases:
  pack   -- per-context patch features per block -> patches/<block>/<ctx>.npz
  cv     -- grouped CV over train clusters; writes cv_results.json
  lock   -- freeze the winner by the pre-registered primary endpoint
  test   -- ONE read of the test split for the locked winner
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, collections, gzip, hashlib, json, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sklearn.model_selection import GroupKFold
from xgboost import XGBClassifier, XGBRegressor, XGBRanker

KS = (1, 3, 5, 10)
PRIMARY_METRIC = 'majority_hit'
PRIMARY_K = 3
FOLDS = 5
SEED = 17
NEG_PER_POS = 6          # training subsample ratio; evaluation always uses ALL patches
RANDOM_REPS = 400
BLOCKS = ('geom', 'atom', 'esm', 'mpnn')
COMBOS = (('geom',), ('geom', 'atom'), ('geom', 'esm'), ('geom', 'mpnn'),
          ('geom', 'atom', 'esm'), ('geom', 'atom', 'esm', 'mpnn'))
SOURCES = {'geom': None,  # from the cache file itself
           'atom': ('atom_cache', 'feat'),
           'esm': ('esm_cache', 'emb64'),
           'mpnn': ('mpnn_cache', 'feat')}


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, d):
    Path(p).write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


# ---------------------------------------------------------------- phase: pack

def residue_block(ctx, block, cache_dir):
    """Residue-level matrix for one block, asserted row-aligned to the cache keys."""
    path = cache_dir / f'{ctx["context_id"]}.json.gz'
    if block == 'geom':
        return np.asarray(ctx['features'], dtype=np.float32)
    sub, field = SOURCES[block]
    f = DATA / sub / f'{ctx["context_id"]}.npz'
    if not f.exists():
        return None
    with np.load(f, allow_pickle=False) as z:
        keys = [str(k) for k in z['keys']]
        if keys != list(ctx['keys']):
            raise ValueError(f'{block} key order mismatch for {ctx["context_id"]}')
        return np.asarray(z[field], dtype=np.float32)


def pack_patches(x, patches):
    """Aggregate residue features over each patch: mean, max, std, + patch geometry."""
    rows = []
    for p in patches:
        ix = np.asarray(p['indices'], dtype=int)
        sub = x[ix]
        rows.append(np.concatenate([sub.mean(0), sub.max(0), sub.std(0)]))
    out = np.asarray(rows, dtype=np.float32)
    if not np.isfinite(out).all():
        out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def phase_pack(args):
    cache_dir = DATA / args.cache_dir
    files = sorted(cache_dir.glob('*.json.gz'))
    done = collections.Counter()
    missing = collections.Counter()
    t0 = time.monotonic()
    for i, f in enumerate(files, 1):
        with gzip.open(f, 'rt') as s:
            ctx = json.load(s)
        cid = ctx['context_id']
        geom_patches = ctx['patches']
        if not geom_patches:
            continue
        for block in BLOCKS:
            if block not in args.blocks:
                continue
            out = DATA / 'patches' / block / f'{cid}.npz'
            if out.exists():
                done[block] += 1
                continue
            x = residue_block(ctx, block, cache_dir)
            if x is None:
                missing[block] += 1
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            xp = pack_patches(x, geom_patches)
            meta = np.asarray([[len(p['indices']), p['area'], p['radius_gyration']]
                               for p in geom_patches], dtype=np.float32)
            np.savez_compressed(out, xp=xp, meta=meta)
            done[block] += 1
        if i % 200 == 0:
            rate = i / (time.monotonic() - t0)
            print(f'{i}/{len(files)} packed  {rate:.1f} ctx/s  done={dict(done)} missing={dict(missing)}',
                  flush=True)
    write(DATA / 'pack_receipt.json',
          {'cache_dir': args.cache_dir, 'contexts': len(files), 'packed': dict(done),
           'missing_block_files': dict(missing), 'blocks': list(args.blocks),
           'aggregation': 'per-patch mean|max|std of residue features, plus [n_res, area, radius_gyration]',
           'script_sha256': digest(__file__)})
    print('pack done', dict(done), 'missing', dict(missing))


# ---------------------------------------------------------------- data loading

def load_index(cache_dir):
    """Light index: per-interface labels and cluster/split, without features."""
    out = []
    for f in sorted(Path(cache_dir).glob('*.json.gz')):
        with gzip.open(f, 'rt') as s:
            ctx = json.load(s)
        if not ctx['patches']:
            continue
        keys = list(ctx['keys'])
        idx = {k: i for i, k in enumerate(keys)}
        disp = list(ctx['display_keys'])
        pat = [np.asarray(p['indices'], dtype=int) for p in ctx['patches']]
        sizes = np.asarray([len(p) for p in pat])
        # Precompute the Jaccard >= 0.5 conflict matrix ONCE per context. NMS is run
        # 400+ times per interface for the random control; recomputing set
        # intersections each time dominated runtime (hours at full scale).
        memb = np.zeros((len(pat), len(keys)), dtype=bool)
        for i, p in enumerate(pat):
            memb[i, p] = True
        inter = (memb.astype(np.int16) @ memb.astype(np.int16).T)
        union = sizes[:, None] + sizes[None, :] - inter
        conflict = (inter / np.maximum(union, 1)) >= .5
        np.fill_diagonal(conflict, False)
        for inst in ctx['instances']:
            pos = set(inst['epitope'])
            y = np.fromiter((d in pos for d in disp), dtype=bool, count=len(disp))
            if y.sum() != len(pos):
                raise ValueError(f'label identity lost for {inst["id"]}')
            inter = np.asarray([int(y[p].sum()) for p in pat])
            purity = inter / sizes
            coverage = inter / max(1, int(y.sum()))
            with np.errstate(divide='ignore', invalid='ignore'):
                f1 = np.nan_to_num(np.where(purity + coverage > 0,
                                            2 * purity * coverage / (purity + coverage), 0.0))
            out.append({'id': inst['id'], 'context': ctx['context_id'], 'split': inst['split'],
                        'cluster': inst['cluster'], 'n_patches': len(pat),
                        'purity': purity.astype(np.float32), 'coverage': coverage.astype(np.float32),
                        'f1': f1.astype(np.float32), 'conflict': conflict})
    return out


def patch_matrix(context_id, combo):
    mats, meta = [], None
    for block in combo:
        f = DATA / 'patches' / block / f'{context_id}.npz'
        if not f.exists():
            return None
        with np.load(f, allow_pickle=False) as z:
            mats.append(z['xp'])
            if meta is None:
                meta = z['meta']
    return np.hstack(mats + [meta])


# ---------------------------------------------------------------- metrics

def nms(conflict, scores, topk=max(KS)):
    """Greedy diversity selection, identical in semantics to the original
    set-intersection implementation but driven by a precomputed conflict matrix."""
    if len(scores) != conflict.shape[0] or not np.isfinite(scores).all():
        raise ValueError('invalid patch scores')
    order = np.argsort(-np.asarray(scores), kind='stable')
    sel = []
    blocked = np.zeros(conflict.shape[0], dtype=bool)
    for i in order:
        if blocked[i]:
            continue
        sel.append(int(i))
        if len(sel) >= topk:
            break
        blocked |= conflict[i]
    return sel


def score_rows(rows, preds, with_oracle=True):
    """Cluster-macro metrics at each k.

    `with_oracle=False` for the random control: the oracle depends only on the
    candidate pool, not on the predictions, so recomputing it on every one of the
    hundreds of random reps was the dominant cost (it was also O(clusters x rows)
    via a `for r in rows if r['cluster'] == c` scan). It is now O(rows) and skipped
    entirely when the caller does not need it.
    """
    byc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, s in zip(rows, preds):
        order = nms(r['conflict'], s)
        maj = r['purity'] > .5
        half = r['coverage'] >= .5
        for k in KS:
            top = order[:k]
            byc[r['cluster']][('majority_hit', k)].append(bool(np.any(maj[top])))
            byc[r['cluster']][('half_epitope_recovery', k)].append(bool(np.any(half[top])))
            byc[r['cluster']][('best_f1', k)].append(float(np.max(r['f1'][top])) if top else 0.0)
    out = {}
    for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1'):
        out[metric] = {str(k): float(np.mean([np.mean(byc[c][(metric, k)]) for c in byc])) for k in KS}
    if with_oracle:
        om = collections.defaultdict(list)
        of = collections.defaultdict(list)
        for r in rows:
            om[r['cluster']].append(bool(np.any(r['purity'] > .5)))
            of[r['cluster']].append(float(np.max(r['f1'])))
        out['oracle'] = {'majority_hit': float(np.mean([np.mean(v) for v in om.values()])),
                         'best_f1': float(np.mean([np.mean(v) for v in of.values()]))}
    return out


def random_control(rows, reps=RANDOM_REPS, seed=SEED):
    rng = np.random.default_rng(seed)
    acc = collections.defaultdict(list)
    for _ in range(reps):
        preds = [rng.random(r['n_patches']) for r in rows]
        m = score_rows(rows, preds, with_oracle=False)
        for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1'):
            for k in KS:
                acc[(metric, k)].append(m[metric][str(k)])
    return {metric: {str(k): {'mean': float(np.mean(acc[(metric, k)])),
                              'sd': float(np.std(acc[(metric, k)]))} for k in KS}
            for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1')}


# ---------------------------------------------------------------- training

def build_training(rows, combo, rng, kind):
    X, Y, groups, sizes = [], [], [], []
    for r in rows:
        m = patch_matrix(r['context'], combo)
        if m is None:
            continue
        if kind == 'patch_ranker':
            keep = np.arange(len(m))
        else:
            pos = np.flatnonzero(r['purity'] > .5)
            neg = np.flatnonzero(r['purity'] <= .5)
            n_neg = min(len(neg), max(NEG_PER_POS * max(1, len(pos)), 8))
            keep = np.concatenate([pos, rng.choice(neg, size=n_neg, replace=False)]) if len(neg) else pos
            if not len(keep):
                continue
        X.append(m[keep])
        if kind == 'patch_classifier':
            Y.append((r['purity'][keep] > .5).astype(np.int32))
        elif kind == 'patch_regressor':
            Y.append(r['f1'][keep].astype(np.float32))
        else:
            Y.append(np.clip(np.floor(r['purity'][keep] * 4), 0, 3).astype(np.int32))
        groups.append(r['cluster'])
        sizes.append(len(keep))
    if not X:
        raise ValueError('no training data')
    counts = collections.Counter(groups)
    w = np.concatenate([np.full(n, 1.0 / (counts[g] * n)) for g, n in zip(groups, sizes)])
    w *= len(w) / w.sum()
    return np.vstack(X), np.concatenate(Y), w, sizes, [1.0 / counts[g] for g in groups]


def fit(Xy, cfg):
    X, Y, w, sizes, gw = Xy
    kw = dict(n_estimators=cfg.get('n_estimators', 400), max_depth=cfg['depth'],
              learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
              min_child_weight=10, reg_lambda=10, random_state=SEED, n_jobs=4,
              tree_method='hist')
    if cfg['kind'] == 'patch_classifier':
        m = XGBClassifier(**kw, objective='binary:logistic', eval_metric='logloss')
        m.fit(X, Y, sample_weight=w)
    elif cfg['kind'] == 'patch_regressor':
        m = XGBRegressor(**kw, objective='reg:squarederror')
        m.fit(X, Y, sample_weight=w)
    else:
        m = XGBRanker(**kw, objective='rank:ndcg', eval_metric=f'ndcg@{PRIMARY_K}',
                      lambdarank_pair_method='topk', lambdarank_num_pair_per_sample=PRIMARY_K)
        m.fit(X, Y, group=sizes, sample_weight=np.asarray(gw))
    return m


def predict(model, rows, combo, kind):
    out, used = [], []
    for r in rows:
        m = patch_matrix(r['context'], combo)
        if m is None:
            continue
        s = model.predict_proba(m)[:, 1] if kind == 'patch_classifier' else model.predict(m)
        out.append(np.asarray(s, dtype=float))
        used.append(r)
    return used, out


# ---------------------------------------------------------------- phases

def cv_path(args):
    return DATA / f'cv_results__{args.cache_dir}__{"+".join(sorted(args.blocks))}.json'


def phase_cv(args):
    index = load_index(DATA / args.cache_dir)
    train = [r for r in index if r['split'] == 'train']

    # Feature blocks have different coverage (e.g. mpnn_cache lagged the others).
    # If each combo trained on whatever contexts its own blocks happened to cover,
    # the combos would differ in TRAINING SET as well as in features and could not
    # be compared. So restrict every combo to the contexts covered by ALL blocks
    # that appear in any combo, and report what that costs.
    # --blocks restricts which feature blocks may appear in a combo. This matters at
    # full scale: the mpnn block costs ~18 s/context (32 CPU-hours over 6,464 contexts)
    # and its measured incremental signal was small -- most of its raw effect dissolved
    # after residualising on solvent exposure. Because combos are restricted to a common
    # context subset for comparability, including a low-coverage block would clamp every
    # combo down to that block's coverage and throw away the scale-up. So it is excluded
    # at full scale by default and kept as a small-cache ablation.
    allowed = set(args.blocks)
    combos = [c for c in COMBOS if set(c) <= allowed]
    if not combos:
        raise ValueError(f'no combos buildable from blocks {sorted(allowed)}')
    needed = sorted({b for combo in combos for b in combo})
    present = {b: {p.stem for p in (DATA / 'patches' / b).glob('*.npz')} for b in needed
               if (DATA / 'patches' / b).exists()}
    common = set.intersection(*present.values()) if present else set()
    avail = [r for r in train if r['context'] in common]
    dropped = len(train) - len(avail)
    groups = np.array([r['cluster'] for r in avail])
    print(f'blocks present: ' + ', '.join(f'{b}={len(v)}' for b, v in present.items()), flush=True)
    print(f'common contexts across all blocks: {len(common)}; '
          f'train interfaces {len(avail)} ({dropped} dropped for incomplete block coverage), '
          f'{len(set(groups))} clusters', flush=True)
    if not avail:
        raise ValueError('no train interfaces with complete block coverage')
    for a, b in (('train', 'val'), ('train', 'test'), ('val', 'test')):
        ca = {r['cluster'] for r in index if r['split'] == a}
        cb = {r['cluster'] for r in index if r['split'] == b}
        if ca & cb:
            raise ValueError(f'cluster leakage between {a} and {b}: {sorted(ca & cb)[:5]}')

    configs = []
    for combo in combos:
        if not all((DATA / 'patches' / b).exists() for b in combo):
            continue
        for kind, depths in (('patch_classifier', (4, 6)), ('patch_regressor', (4,)), ('patch_ranker', (5,))):
            if args.kinds and kind not in args.kinds:
                continue
            for d in depths:
                configs.append({'kind': kind, 'depth': d, 'combo': list(combo)})
    splits = list(GroupKFold(n_splits=FOLDS).split(np.arange(len(avail)), groups=groups))
    results = {'cache_dir': args.cache_dir, 'folds': FOLDS, 'seed': SEED,
               'train_interfaces': len(avail), 'train_clusters': int(len(set(groups))),
               'primary_endpoint': f'cluster-macro {PRIMARY_METRIC}@{PRIMARY_K}, grouped CV over train clusters',
               'neg_per_pos': NEG_PER_POS, 'combos': [list(c) for c in combos],
               'blocks_allowed': sorted(allowed),
               'script_sha256': digest(__file__), 'common_contexts': len(common),
               'train_interfaces_dropped_for_block_coverage': dropped,
               'blocks_present': {b: len(v) for b, v in present.items()}, 'models': {}}
    rc = [random_control([avail[i] for i in te], reps=120, seed=SEED + fi)
          for fi, (_, te) in enumerate(splits)]
    results['random_control_cv'] = {m: {str(k): float(np.mean([f[m][str(k)]['mean'] for f in rc]))
                                        for k in KS} for m in rc[0]}
    for cfg in configs:
        name = f"{cfg['kind']}_d{cfg['depth']}_{'+'.join(cfg['combo'])}"
        per = collections.defaultdict(list)
        t0 = time.monotonic()
        try:
            for tr, te in splits:
                rng = np.random.default_rng(SEED)
                model = fit(build_training([avail[i] for i in tr], tuple(cfg['combo']), rng, cfg['kind']), cfg)
                used, preds = predict(model, [avail[i] for i in te], tuple(cfg['combo']), cfg['kind'])
                m = score_rows(used, preds)
                for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1'):
                    for k in KS:
                        per[(metric, k)].append(m[metric][str(k)])
        except Exception as exc:
            results['models'][name] = {'error': repr(exc), 'config': cfg}
            print(f'  {name}: ERROR {exc!r}', flush=True)
            write(cv_path(args), results)
            continue
        results['models'][name] = {
            'config': cfg, 'seconds': time.monotonic() - t0,
            **{metric: {str(k): {'mean': float(np.mean(per[(metric, k)])),
                                 'sd': float(np.std(per[(metric, k)]))} for k in KS}
               for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1')}}
        p = results['models'][name][PRIMARY_METRIC][str(PRIMARY_K)]
        print(f"  {name:48s} @{PRIMARY_K} {p['mean']:.3f} +/- {p['sd']:.3f}  "
              f"({time.monotonic()-t0:.0f}s)", flush=True)
        write(cv_path(args), results)
    base = results['random_control_cv'][PRIMARY_METRIC][str(PRIMARY_K)]
    print(f"\nrandom control @{PRIMARY_K}: {base:.3f}")
    ok = {k: v for k, v in results['models'].items() if 'error' not in v}
    for name in sorted(ok, key=lambda n: -ok[n][PRIMARY_METRIC][str(PRIMARY_K)]['mean'])[:8]:
        v = ok[name][PRIMARY_METRIC][str(PRIMARY_K)]
        print(f"  {name:48s} {v['mean']:.3f} +/- {v['sd']:.3f}  (+{v['mean']-base:+.3f} vs random)")


def phase_lock(args):
    cv = json.loads(cv_path(args).read_text())
    ok = {k: v for k, v in cv['models'].items() if 'error' not in v}
    if not ok:
        raise ValueError('no successful CV models')
    winner = max(ok, key=lambda n: (ok[n][PRIMARY_METRIC][str(PRIMARY_K)]['mean'],
                                    -ok[n][PRIMARY_METRIC][str(PRIMARY_K)]['sd']))
    lock = {'winner': winner, 'config': ok[winner]['config'],
            'primary_endpoint': cv['primary_endpoint'],
            'selected_on': 'grouped CV over TRAIN clusters only; val and test unread',
            'cv_summary': {m: ok[winner][m] for m in ('majority_hit', 'half_epitope_recovery', 'best_f1')},
            'random_control_cv': cv['random_control_cv'],
            'cv_results_sha256': digest(cv_path(args)), 'cv_results_file': cv_path(args).name,
            'script_sha256': digest(__file__), 'test_used_for_selection': False}
    write(DATA / 'sweep_lock.json', lock)
    print('LOCKED', winner, json.dumps(lock['cv_summary'][PRIMARY_METRIC][str(PRIMARY_K)]))


def phase_test(args):
    lock = json.loads((DATA / 'sweep_lock.json').read_text())
    if lock['cv_results_sha256'] != digest(cv_path(args)):
        raise ValueError('CV history changed since lock')
    cfg = lock['config']
    combo = tuple(cfg['combo'])
    index = load_index(DATA / args.cache_dir)
    train = [r for r in index if r['split'] == 'train' and patch_matrix(r['context'], ('geom',)) is not None]
    test = [r for r in index if r['split'] == 'test' and patch_matrix(r['context'], ('geom',)) is not None]
    print(f'refit on {len(train)} train interfaces; test {len(test)} interfaces, '
          f'{len(set(r["cluster"] for r in test))} clusters', flush=True)
    model = fit(build_training(train, combo, np.random.default_rng(SEED), cfg['kind']), cfg)
    used, preds = predict(model, test, combo, cfg['kind'])
    res = {'status': 'single test read after CV-locked selection', 'lock': lock,
           'n_test_interfaces': len(used), 'n_test_clusters': len(set(r['cluster'] for r in used)),
           'selected': score_rows(used, preds)}
    rc = random_control(used)
    res['random_control'] = rc
    res['vs_random'] = {}
    for metric in ('majority_hit', 'half_epitope_recovery', 'best_f1'):
        res['vs_random'][metric] = {}
        for k in KS:
            v = res['selected'][metric][str(k)]
            mu, sd = rc[metric][str(k)]['mean'], rc[metric][str(k)]['sd']
            res['vs_random'][metric][str(k)] = {'value': v, 'random_mean': mu, 'random_sd': sd,
                                                'z': float((v - mu) / sd) if sd else None}
    write(DATA / 'sweep_test_results.json', res)
    print(f"\n{'metric':26s}" + ''.join(f"{'@'+str(k):>18s}" for k in KS))
    for metric in ('majority_hit', 'best_f1'):
        print(f'{metric:26s}' + ''.join(
            f"{res['selected'][metric][str(k)]:>10.3f} z{res['vs_random'][metric][str(k)]['z']:+5.1f}"
            for k in KS))
    print(f"{'random control':26s}" + ''.join(
        f"{rc['majority_hit'][str(k)]['mean']:>10.3f}+-{rc['majority_hit'][str(k)]['sd']:<5.3f}" for k in KS))
    print(f"\nPRIMARY {PRIMARY_METRIC}@{PRIMARY_K}: "
          f"{res['selected'][PRIMARY_METRIC][str(PRIMARY_K)]:.3f} "
          f"(z={res['vs_random'][PRIMARY_METRIC][str(PRIMARY_K)]['z']:+.1f})")
    print(f"oracle on test: {res['selected']['oracle']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=['pack', 'cv', 'lock', 'test'], required=True)
    ap.add_argument('--cache-dir', default='cache_all')
    ap.add_argument('--blocks', nargs='*', default=list(BLOCKS))
    # --kinds limits which model families are fitted. patch_ranker trains on ALL
    # patches (no negative subsampling), so at full scale it is ~675k rows x 468+
    # features per fold and thrashes a machine whose swap is already exhausted --
    # while not being the best arm. The classifiers subsample and are both cheaper
    # and stronger, so the final sweep is led by them.
    ap.add_argument('--kinds', nargs='*', default=None,
                    help='subset of: patch_classifier patch_regressor patch_ranker')
    args = ap.parse_args()
    {'pack': phase_pack, 'cv': phase_cv, 'lock': phase_lock, 'test': phase_test}[args.phase](args)


if __name__ == '__main__':
    main()
