#!/usr/bin/env python
"""Design-level minibinder designability model from site/footprint features.

Pre-registers the protocol (hash printed before any fit), then runs strict
leave-one-target-out CV at design-level resolution over the Anthropic/Adaptyv
binder dataset.

Run with the research environment described in docs/reproducibility.md. Writes only to
$PRINCE_DATA_DIR/designability_train/.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu, spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

MAP_CSV = DATA / 'site_benchmark' / 'design_site_map.csv'
SITE_CSV = DATA / 'site_benchmark' / 'site_benchmark.csv'
TGT_DIR = DATA / 'site_scoring' / 'targets'
OUT = DATA / 'designability_train'
SEED = 20261011

# 51 per-residue feature names, read from the cache builder (not retyped).
BUILDER = Path(__file__).with_name('build_cache_all.py')


def feature_names() -> list[str]:
    """Lift the 51 feature names verbatim out of build_cache_all.py.

    Takes the contiguous AA/BASE/FEATURES block (lines 29-33) and executes it,
    so the order can never drift from the cache builder.
    """
    lines = BUILDER.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('AA = ['))
    end = next(i for i, l in enumerate(lines[start:], start)
               if l.startswith('    FEATURES += [f\'r{radius}')) + 1
    block = '\n'.join(lines[start:end])
    assert "FEATURES = BASE" in block and 'for radius in' in block, block
    ns: dict = {}
    exec(block, ns)
    feats = ns['FEATURES']
    assert len(feats) == 51, f'expected 51 features, parsed {len(feats)}'
    return list(feats)


FEATURES = feature_names()
STATS = ('mean', 'max', 'min', 'std')
GEOM = ['fp_radius_of_gyration', 'fp_max_pairwise_dist',
        'fp_shape_anisotropy', 'fp_shape_planarity', 'fp_shape_linearity']
PIPELINE_CAT = ['generator', 'design_model', 'campaign',
                'sequence_design_method', 'source_file_kind']
PRIMARY7 = ['PD-L1', 'TNFa', 'TrkA', 'EGFR', 'TREM2', 'BHRF1', 'IL-7Ra']
NEAR_DEGENERATE = ['15-PGDH', 'BBF-14']

XGB_KW = dict(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
              colsample_bytree=0.8, min_child_weight=20, reg_lambda=10,
              tree_method='hist', random_state=SEED, n_jobs=2,
              eval_metric='logloss')


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def predeclare() -> str:
    doc = {
        'experiment': 'design-level minibinder designability from site/footprint features',
        'date': '2026-10-12',
        'data': {
            'rows': 'design_site_map.csv, 1307 designs, 15 targets',
            'label': "binder_final (string True/False) -> binary; 353 True / 954 False",
        },
        'primary_endpoint': ('macro-mean of WITHIN-TARGET design-level ROC AUC over '
                             'leave-one-target-out predictions, across targets with both '
                             'classes present (MBP excluded: 0/90 positives). Reported with '
                             'sd across targets and a variant excluding near-degenerate '
                             'targets 15-PGDH (1/30) and BBF-14 (3/90).'),
        'secondary_endpoint': ('within-target Spearman rho between per-site MEAN predicted '
                               'probability and site observed success_rate, sites with '
                               'n_designs>=5, on the 7 primary targets '
                               '(PD-L1, TNFa, TrkA, EGFR, TREM2, BHRF1, IL-7Ra).'),
        'pooled_scoring': 'FORBIDDEN as a result. Reported only beside the target-mean-only baseline and labelled invalid.',
        'cv': 'strict leave-one-target-out over all 15 targets; no target informs its own predictions',
        'primary_model': {'estimator': 'xgboost.XGBClassifier', 'params': XGB_KW,
                          'tuning': 'NONE - hyperparameters declared a priori'},
        'secondary_models': [
            {'estimator': 'sklearn LogisticRegression', 'params': {'C': 1.0, 'penalty': 'l2',
             'max_iter': 5000}, 'scaling': 'StandardScaler fitted on TRAIN folds only'},
            {'estimator': 'sklearn DecisionTreeClassifier', 'params': {'max_depth': 2,
             'random_state': SEED}},
        ],
        'features': {
            'base': ('51 per-residue features (FEATURES in build_cache_all.py) aggregated over '
                     'the design footprint with mean/max/min/std = 204 columns'),
            'geometric': GEOM,
            'hygiene': [
                'DROP all 4 statistics of log_target_residues (pure target-identity channel)',
                'DROP any aggregated column that is constant within every target',
                'EXCLUDE footprint size from the primary arm (binder 9.63 vs non-binder 9.80, MWU p=0.00085)',
                'EXCLUDE design-pipeline columns from the primary arm: '
                'generator, design_model, campaign, sequence_design_method, binder_length, source_file_kind',
            ],
        },
        'arms': {
            'primary': 'site/footprint features only, after hygiene',
            'sensitivity_size': 'primary + footprint size (n residues)',
            'secondary_pipeline': 'primary + one-hot design-pipeline columns + binder_length',
        },
        'controls': [
            'label shuffle WITHIN target, 200 reps, full LOTO rerun each rep (the null that matters)',
            'random scores',
            'unfitted exposure: footprint mean relative_sasa as the score (baseline to beat)',
            'target-mean-only predictor (upper bound on what target identity alone buys)',
        ],
        'honesty_rule': ("a primary macro AUC inside the label-shuffle null's 95% interval IS a "
                         'null and will be reported as such'),
        'deviations_from_brief': [
            {'what': 'footprint coverage tolerance',
             'brief_assumed': 'footprints map cleanly through pos2res for all rows',
             'found': ('141/1307 designs contain >=1 construct position unresolved in the '
                       'deposited structure, so pos2res has no entry. Requiring a complete '
                       'footprint is label-associated: TREM2 loses 7 binders vs 1 non-binder, '
                       'Nipah-G loses 64 rows.'),
             'change': ('aggregate over resolved residues; require coverage >=0.6 and >=5 '
                        'resolved positions'),
             'numeric_justification': ('keeps 1301/1307 rows, positive rate 0.271 vs 0.270 '
                                       'for the full file, vs 1166 rows / 0.272 under the '
                                       'strict rule; a strict coverage==1.0 sensitivity arm '
                                       'is reported alongside the primary'),
             'discovered': 'during the join diagnostic, before any model was fitted'},
            {'what': 'homomer symmetry copies',
             'found': ('TNFa (trimer) and Latent GDF-8 (dimer) map one construct position to '
                       '2-3 structure residues; 142/157 TNFa positions have multiplicity 3'),
             'change': ('select the single chain covering the most footprint positions per '
                        'design (ties -> lexicographically first), one residue per position'),
             'numeric_justification': ('taking all copies spreads a 10-residue footprint over '
                                       '30 residues across the whole assembly, which turns the '
                                       'geometric descriptors (Rg, max pairwise distance) into '
                                       'a target-identity channel'),
             'discovered': 'during the join diagnostic, before any model was fitted'},
        ],
        'random_state': SEED,
        'inputs_sha256': {
            'design_site_map.csv': sha256(MAP_CSV),
            'site_benchmark.csv': sha256(SITE_CSV),
            'build_cache_all.py': sha256(BUILDER),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(doc, indent=2, sort_keys=True)
    (OUT / 'predeclaration.json').write_text(txt)
    return hashlib.sha256(txt.encode()).hexdigest()


# ---------------------------------------------------------------- data loading

def load_targets() -> dict:
    out = {}
    for jf in sorted(TGT_DIR.glob('*.json')):
        meta = json.loads(jf.read_text())
        z = np.load(jf.with_suffix('.npz'))
        key_idx = {k: i for i, k in enumerate(meta['keys'])}
        out[jf.stem] = {'meta': meta, 'F': z['F'], 'C': z['C'], 'key_idx': key_idx,
                        'npz_sha': sha256(jf.with_suffix('.npz')),
                        'json_sha': sha256(jf)}
    return out


def shape_ratios(cloud: np.ndarray) -> tuple[float, float, float]:
    c = cloud - cloud.mean(0, keepdims=True)
    eig = np.linalg.eigvalsh(c.T @ c / max(1, len(cloud)))  # ascending l1<=l2<=l3
    top = max(eig[2], 1e-9)
    return (float((eig[2] - eig[0]) / top),      # anisotropy
            float((eig[1] - eig[0]) / top),      # planarity
            float((eig[2] - eig[1]) / top))      # linearity


def build() -> dict:
    tg = load_targets()
    rows = list(csv.DictReader(MAP_CSV.open()))
    counts = {'csv_rows': len(rows)}

    agg_names = [f'{s}_{f}' for s in STATS for f in FEATURES]
    X, Xg, y, meta_rows = [], [], [], []
    drop_reasons = {'no_target_file': 0, 'no_label': 0, 'empty_footprint': 0,
                    'unmapped_residue': 0, 'low_footprint_coverage': 0}

    for r in rows:
        tname = r['target'].replace(' ', '_')
        if tname not in tg:
            drop_reasons['no_target_file'] += 1
            continue
        if r['binder_final'] not in ('True', 'False'):
            drop_reasons['no_label'] += 1
            continue
        fp = [p for p in r['footprint_residues'].split(';') if p]
        if not fp:
            drop_reasons['empty_footprint'] += 1
            continue
        t = tg[tname]
        p2r, ki = t['meta']['pos2res'], t['key_idx']
        # DEVIATION 1 (documented): some construct positions are unresolved in the
        # deposited structure, so pos2res has no entry. Requiring a complete
        # footprint drops 141/1307 rows and is label-associated (TREM2 loses 7
        # binders vs 1 non-binder). Instead: aggregate over the RESOLVED residues
        # and require >=60% coverage and >=5 resolved positions. That keeps
        # 1301/1307 rows at an unchanged positive rate (0.271 vs 0.270).
        # DEVIATION 2 (documented): for homomers (TNFa trimer, Latent GDF-8 dimer)
        # one construct position maps to 2-3 symmetry copies. Taking all of them
        # would spread the "footprint" across the whole assembly and make the
        # geometric descriptors a target-identity channel, so one dominant chain
        # is selected per design.
        cand = {p: p2r[str(p)] for p in fp if str(p) in p2r}
        if not cand:
            drop_reasons['unmapped_residue'] += 1
            continue
        chain_hits: dict[str, int] = {}
        for ent in cand.values():
            for chain, _ in ent:
                chain_hits[chain] = chain_hits.get(chain, 0) + 1
        dom = min(chain_hits, key=lambda c: (-chain_hits[c], c))
        idx = []
        for p, ent in cand.items():
            pick = next((e for e in ent if e[0] == dom), ent[0])
            k = f'{pick[0]}{pick[1]}'
            if k in ki:
                idx.append(ki[k])
        coverage = len(idx) / len(fp)
        if coverage < 0.6 or len(idx) < 5:
            drop_reasons['low_footprint_coverage'] += 1
            continue
        idx = sorted(set(idx))
        F = t['F'][idx]
        X.append(np.concatenate([F.mean(0), F.max(0), F.min(0), F.std(0)]))
        cl = t['C'][idx]
        rg = float(np.sqrt(((cl - cl.mean(0)) ** 2).sum(1).mean()))
        d = np.linalg.norm(cl[:, None, :] - cl[None, :, :], axis=-1)
        a, pl, li = shape_ratios(cl)
        Xg.append([rg, float(d.max()), a, pl, li])
        y.append(1 if r['binder_final'] == 'True' else 0)
        meta_rows.append({'uuid': r['uuid'], 'target': r['target'], 'site_id': r['site_id'],
                          'fp_size': len(idx), 'coverage': coverage,
                          'fp_declared': len(fp),
                          **{c: r[c] for c in PIPELINE_CAT},
                          'binder_length': float(r['binder_length'] or 'nan')})

    X = np.hstack([np.asarray(X, float), np.asarray(Xg, float)])
    names = agg_names + GEOM
    y = np.asarray(y, int)
    tgts = np.asarray([m['target'] for m in meta_rows])
    counts['joined_rows'] = len(y)
    counts['drop_reasons'] = drop_reasons
    counts['positives'] = int(y.sum())
    counts['negatives'] = int((1 - y).sum())

    # ---- hygiene
    dropped = {}
    keep = np.ones(X.shape[1], bool)
    for i, n in enumerate(names):
        if n.endswith('_log_target_residues'):
            keep[i] = False
            dropped[n] = 'target-identity channel (declared drop)'
    uts = np.unique(tgts)
    for i, n in enumerate(names):
        if not keep[i]:
            continue
        if all(np.ptp(X[tgts == t, i]) == 0 for t in uts):
            keep[i] = False
            dropped[n] = 'constant within every target'
    Xp = X[:, keep]
    kept = [n for n, k in zip(names, keep) if k]
    counts['n_features_built'] = len(names)
    counts['n_features_primary'] = len(kept)

    return dict(X=Xp, names=kept, y=y, tgts=tgts, rows=meta_rows, dropped=dropped,
                counts=counts, tg_sha={k: (v['npz_sha'], v['json_sha']) for k, v in tg.items()},
                relsasa_col=kept.index('mean_relative_sasa'))


# -------------------------------------------------------------------- fitting

def loto(X, y, tgts, kind='xgb'):
    """Out-of-fold predicted probabilities under strict leave-one-target-out."""
    oof = np.full(len(y), np.nan)
    for t in np.unique(tgts):
        te = tgts == t
        tr = ~te
        if len(np.unique(y[tr])) < 2:
            continue
        if kind == 'xgb':
            m = XGBClassifier(**XGB_KW)
            m.fit(X[tr], y[tr])
            oof[te] = m.predict_proba(X[te])[:, 1]
        elif kind == 'lr':
            sc = StandardScaler().fit(X[tr])
            m = LogisticRegression(C=1.0, penalty='l2', max_iter=5000)
            m.fit(sc.transform(X[tr]), y[tr])
            oof[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
        elif kind == 'tree':
            m = DecisionTreeClassifier(max_depth=2, random_state=SEED)
            m.fit(X[tr], y[tr])
            oof[te] = m.predict_proba(X[te])[:, 1]
    return oof


def per_target_auc(score, y, tgts):
    out = {}
    for t in np.unique(tgts):
        m = tgts == t
        yy, ss = y[m], score[m]
        if len(np.unique(yy)) < 2 or not np.isfinite(ss).all():
            out[t] = None
        else:
            out[t] = float(roc_auc_score(yy, ss))
    return out


def macro(aucs, exclude=()):
    v = [a for t, a in aucs.items() if a is not None and t not in exclude]
    return (float(np.mean(v)), float(np.std(v, ddof=1)) if len(v) > 1 else float('nan'), len(v))


def site_rho(score, y, tgts, rows, site_sr):
    """Within-target Spearman: per-site mean predicted prob vs observed success_rate."""
    res = {}
    for t in PRIMARY7:
        m = tgts == t
        sites = {}
        for i in np.where(m)[0]:
            sites.setdefault(rows[i]['site_id'], []).append(i)
        xs, ys = [], []
        for sid, ii in sites.items():
            if len(ii) < 5 or sid not in site_sr:
                continue
            if not np.isfinite(score[ii]).all():
                continue
            xs.append(float(np.mean(score[ii])))
            ys.append(site_sr[sid])
        if len(xs) >= 3:
            r, p = spearmanr(xs, ys)
            res[t] = {'rho': float(r), 'p': float(p), 'n_sites': len(xs)}
        else:
            res[t] = {'rho': None, 'p': None, 'n_sites': len(xs)}
    vals = [v['rho'] for v in res.values() if v['rho'] is not None]
    return res, (float(np.mean(vals)) if vals else float('nan')), len(vals)


def main():
    t0 = time.time()
    pre = predeclare()
    print(f'PREDECLARATION sha256 = {pre}')
    print(f'  written to {OUT / "predeclaration.json"}')
    sys.stdout.flush()

    D = build()
    X, y, tgts, rows, names = D['X'], D['y'], D['tgts'], D['rows'], D['names']
    print(f"rows joined: {D['counts']['joined_rows']}  pos={D['counts']['positives']}  "
          f"neg={D['counts']['negatives']}")
    print(f"features: built {D['counts']['n_features_built']} -> primary {len(names)} "
          f"({len(D['dropped'])} dropped)")
    sys.stdout.flush()

    site_sr = {}
    for r in csv.DictReader(SITE_CSV.open()):
        try:
            site_sr[r['site_id']] = float(r['success_rate'])
        except (TypeError, ValueError):
            pass

    fp_size = np.asarray([r['fp_size'] for r in rows], float)
    res = {'predeclaration_sha256': pre, 'counts': D['counts'],
           'dropped_features': D['dropped'], 'feature_names_primary': names}

    # ---- arms
    arms = {'primary': (X, names)}
    arms['sensitivity_size'] = (np.hstack([X, fp_size[:, None]]), names + ['fp_size'])

    cats, cnames = [], []
    for c in PIPELINE_CAT:
        vals = sorted({r[c] for r in rows})
        for v in vals:
            cats.append([1.0 if r[c] == v else 0.0 for r in rows])
            cnames.append(f'{c}={v}')
    bl = np.asarray([r['binder_length'] for r in rows], float)
    bl = np.nan_to_num(bl, nan=float(np.nanmedian(bl)))
    arms['secondary_pipeline'] = (np.hstack([X, np.asarray(cats, float).T, bl[:, None]]),
                                  names + cnames + ['binder_length'])

    res['arms'] = {}
    oof_primary = None
    for arm, (Xa, na) in arms.items():
        res['arms'][arm] = {'n_features': len(na)}
        for kind in ('xgb', 'lr', 'tree'):
            if arm != 'primary' and kind != 'xgb':
                continue
            oof = loto(Xa, y, tgts, kind)
            aucs = per_target_auc(oof, y, tgts)
            mu, sd, n = macro(aucs)
            mu2, sd2, n2 = macro(aucs, exclude=NEAR_DEGENERATE)
            rho, rho_mean, rho_n = site_rho(oof, y, tgts, rows, site_sr)
            ok = np.isfinite(oof)
            res['arms'][arm][kind] = {
                'per_target_auc': aucs,
                'macro_auc': mu, 'macro_sd': sd, 'n_targets': n,
                'n_targets_above_0.5': sum(1 for a in aucs.values() if a is not None and a > .5),
                'macro_auc_ex_near_degenerate': mu2, 'macro_sd_ex': sd2, 'n_ex': n2,
                'site_rho_per_target': rho, 'site_rho_mean': rho_mean, 'site_rho_n_targets': rho_n,
                'POOLED_AUC_INVALID': float(roc_auc_score(y[ok], oof[ok])),
            }
            print(f'  [{arm}/{kind}] macro AUC = {mu:.4f} (sd {sd:.4f}, n={n}); '
                  f'ex-degenerate {mu2:.4f} (n={n2}); site rho mean {rho_mean:.4f}')
            sys.stdout.flush()
            if arm == 'primary' and kind == 'xgb':
                oof_primary = oof
    np.save(OUT / 'oof_primary_xgb.npy', oof_primary)

    # ---- controls
    res['controls'] = {}
    rng = np.random.default_rng(SEED)

    rs = rng.random(len(y))
    a = per_target_auc(rs, y, tgts)
    mu, sd, n = macro(a)
    rho, rm, rn = site_rho(rs, y, tgts, rows, site_sr)
    res['controls']['random_scores'] = {'macro_auc': mu, 'macro_sd': sd, 'n_targets': n,
                                        'per_target_auc': a, 'site_rho_mean': rm}
    print(f'  [control random] macro AUC = {mu:.4f} (sd {sd:.4f})')

    exposure = X[:, D['relsasa_col']]
    a = per_target_auc(exposure, y, tgts)
    mu, sd, n = macro(a)
    mu2, sd2, n2 = macro(a, exclude=NEAR_DEGENERATE)
    rho, rm, rn = site_rho(exposure, y, tgts, rows, site_sr)
    res['controls']['unfitted_exposure'] = {
        'score': 'footprint mean relative_sasa', 'macro_auc': mu, 'macro_sd': sd,
        'n_targets': n, 'per_target_auc': a,
        'n_targets_above_0.5': sum(1 for v in a.values() if v is not None and v > .5),
        'macro_auc_ex_near_degenerate': mu2,
        'site_rho_per_target': rho, 'site_rho_mean': rm,
        'POOLED_AUC_INVALID': float(roc_auc_score(y, exposure))}
    print(f'  [control exposure] macro AUC = {mu:.4f} (sd {sd:.4f}); site rho mean {rm:.4f}')

    tmean = np.asarray([y[tgts == t].mean() for t in tgts])
    a = per_target_auc(tmean, y, tgts)
    rho, rm, rn = site_rho(tmean, y, tgts, rows, site_sr)
    res['controls']['target_mean_only'] = {
        'note': ('constant within a target, so within-target AUC is 0.5 by construction; '
                 'the pooled numbers below show what target identity alone buys and are '
                 'the reason pooled scoring is invalid'),
        'within_target_auc': {t: (None if v is None else float(v)) for t, v in a.items()},
        'POOLED_AUC_INVALID': float(roc_auc_score(y, tmean)),
        'POOLED_SPEARMAN_INVALID': float(spearmanr(tmean, y).statistic),
        'site_rho_mean': rm}
    print(f"  [control target-mean] pooled AUC (INVALID) = "
          f"{res['controls']['target_mean_only']['POOLED_AUC_INVALID']:.4f}")
    sys.stdout.flush()

    # footprint size check (why it is excluded)
    u = mannwhitneyu(fp_size[y == 1], fp_size[y == 0])
    res['footprint_size_check'] = {'mean_binder': float(fp_size[y == 1].mean()),
                                   'mean_nonbinder': float(fp_size[y == 0].mean()),
                                   'mwu_p': float(u.pvalue)}

    # ---- label shuffle within target, 200 reps
    NREP = 200
    print(f'  [control label-shuffle] running {NREP} reps of full LOTO ...')
    sys.stdout.flush()
    null_macro, null_macro_ex, null_rho = [], [], []
    for rep in range(NREP):
        ys = y.copy()
        for t in np.unique(tgts):
            m = np.where(tgts == t)[0]
            ys[m] = rng.permutation(y[m])
        oof = loto(X, ys, tgts, 'xgb')
        a = per_target_auc(oof, ys, tgts)
        null_macro.append(macro(a)[0])
        null_macro_ex.append(macro(a, exclude=NEAR_DEGENERATE)[0])
        null_rho.append(site_rho(oof, ys, tgts, rows, site_sr)[1])
        if (rep + 1) % 25 == 0:
            print(f'    rep {rep+1}/{NREP}  running mean {np.mean(null_macro):.4f} '
                  f'({time.time()-t0:.0f}s)')
            sys.stdout.flush()
    nm = np.asarray(null_macro)
    nme = np.asarray(null_macro_ex)
    obs = res['arms']['primary']['xgb']['macro_auc']
    obs_ex = res['arms']['primary']['xgb']['macro_auc_ex_near_degenerate']
    res['controls']['label_shuffle_within_target'] = {
        'n_reps': NREP, 'mean': float(nm.mean()), 'sd': float(nm.std(ddof=1)),
        'ci95': [float(np.percentile(nm, 2.5)), float(np.percentile(nm, 97.5))],
        'observed_primary_macro_auc': obs,
        'p_one_sided': float((nm >= obs).sum() + 1) / (NREP + 1),
        'observed_inside_null_ci95': bool(np.percentile(nm, 2.5) <= obs <= np.percentile(nm, 97.5)),
        'ex_degenerate': {'mean': float(nme.mean()), 'sd': float(nme.std(ddof=1)),
                          'ci95': [float(np.percentile(nme, 2.5)), float(np.percentile(nme, 97.5))],
                          'observed': obs_ex,
                          'p_one_sided': float((nme >= obs_ex).sum() + 1) / (NREP + 1),
                          'observed_inside_null_ci95': bool(
                              np.percentile(nme, 2.5) <= obs_ex <= np.percentile(nme, 97.5))},
        'site_rho_null_mean': float(np.nanmean(null_rho)),
        'site_rho_null_ci95': [float(np.nanpercentile(null_rho, 2.5)),
                               float(np.nanpercentile(null_rho, 97.5))],
    }
    np.save(OUT / 'null_macro_auc.npy', nm)

    # ---- strict-coverage sensitivity arm (complete footprints only)
    strict = np.asarray([r['coverage'] >= 0.999 for r in rows])
    oofs = loto(X[strict], y[strict], tgts[strict], 'xgb')
    a = per_target_auc(oofs, y[strict], tgts[strict])
    mu, sd, n = macro(a)
    res['arms']['strict_complete_footprint'] = {
        'n_rows': int(strict.sum()), 'n_features': len(names),
        'xgb': {'per_target_auc': a, 'macro_auc': mu, 'macro_sd': sd, 'n_targets': n,
                'macro_auc_ex_near_degenerate': macro(a, exclude=NEAR_DEGENERATE)[0],
                'n_targets_above_0.5': sum(1 for v in a.values() if v is not None and v > .5)}}
    print(f'  [strict-coverage/xgb] n={strict.sum()} macro AUC = {mu:.4f} (sd {sd:.4f}, n={n})')
    cov = np.asarray([r['coverage'] for r in rows])
    res['coverage'] = {'mean': float(cov.mean()), 'min': float(cov.min()),
                       'frac_complete': float((cov >= 0.999).mean()),
                       'mean_binder': float(cov[y == 1].mean()),
                       'mean_nonbinder': float(cov[y == 0].mean())}
    sys.stdout.flush()

    res['receipt'] = {
        'python': sys.version,
        'inputs_sha256': {'design_site_map.csv': sha256(MAP_CSV),
                          'site_benchmark.csv': sha256(SITE_CSV),
                          'build_cache_all.py': sha256(BUILDER)},
        'target_cache_sha256': {k: {'npz': v[0], 'json': v[1]} for k, v in D['tg_sha'].items()},
        'runtime_s': time.time() - t0,
    }
    (OUT / 'results.json').write_text(json.dumps(res, indent=2, sort_keys=True, default=str))

    with (OOUT := OUT / 'per_target_auc.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['target', 'n_designs', 'n_binders', 'auc_primary_xgb',
                    'auc_unfitted_exposure', 'auc_lr', 'auc_tree'])
        px = res['arms']['primary']['xgb']['per_target_auc']
        pe = res['controls']['unfitted_exposure']['per_target_auc']
        pl = res['arms']['primary']['lr']['per_target_auc']
        pt = res['arms']['primary']['tree']['per_target_auc']
        for t in sorted(np.unique(tgts)):
            m = tgts == t
            w.writerow([t, int(m.sum()), int(y[m].sum()), px.get(t), pe.get(t),
                        pl.get(t), pt.get(t)])

    print()
    print(f'PRIMARY macro AUC = {obs:.4f} (sd {res["arms"]["primary"]["xgb"]["macro_sd"]:.4f})')
    nullrec = res['controls']['label_shuffle_within_target']
    print(f'NULL (label shuffle) = {nullrec["mean"]:.4f}  CI95 {nullrec["ci95"]}  '
          f'p={nullrec["p_one_sided"]:.4f}  inside_null={nullrec["observed_inside_null_ci95"]}')
    print(f'wrote {OUT / "results.json"}, {OOUT}')
    print(f'total {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
