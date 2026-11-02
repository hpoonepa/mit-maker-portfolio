"""Score PRINCE site scores against the minibinder-designability benchmark.

The question: does PRINCE's patch score order a target's OWN sites by the rate
at which de novo minibinders designed there actually bound in the lab?

Non-negotiables implemented here, all of them from the benchmark's own receipt
(site_benchmark/RECEIPT.txt, "RECOMMENDED EVALUATION -- binding rules, not
suggestions"):

* **Within-target only.** Between-target variance exceeds between-site
  variance, and a predictor that emits nothing but its target's mean success
  rate scores Spearman rho = 0.750 on the pooled estimable rows. A pooled
  correlation is target recognition. Every number here is per-target Spearman,
  aggregated afterwards.
* **Stripped structures only.** `*_chosen_stripped.pdb` -- partners removed,
  empty unit cell, P 1. The deposited files bury exactly the bindable sites and
  would correlate the artifact with the label.
* **Leakage first.** PRINCE is trained on antibody-antigen interfaces and
  several benchmark targets are famous antigens. Clusters whose antigen matches
  a benchmark target are removed from training and the primary model is the one
  retrained without them; the contaminated model is reported beside it, never
  as the headline.
* **Controls.** Random patch scores give the null distribution of per-target
  rho. Exposure alone is reported too, because it was measured to be actively
  anti-predictive for antibody epitopes and a different sign here would matter.

Feature code is not reimplemented: the 51 residue features are the literal
FEATURES list of build_cache_all.py (asserted equal to the cached
`feature_names` of every cache_all context before anything is scored), and the
patch-level aggregation, the training-set assembly and the XGBoost fit are
imported from sweep.py so the benchmark is scored by the same code that trained
the models.

Run with the research environment described in docs/reproducibility.md. Outputs to prince-data/site_scoring.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import collections
import gzip
import hashlib
import json
import os
import pickle
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
CODE = REPO
BENCH = (DATA / "site_benchmark")
OUT = (DATA / "site_scoring")
CACHE_ALL = (DATA / "cache_all")

sys.path[:0] = [str(CODE / 'src'), str(CODE)]
sys.path.insert(0, str(HERE))

import gemmi  # noqa: E402
import sweep as SW  # noqa: E402  (verbatim patch packing / training / fit)
from hotspot_preflight.structure import load_target  # noqa: E402
from hotspot_preflight.predict.geometric import GeometricPredictor  # noqa: E402
from hotspot_preflight.predict.features import residue_names, residue_points  # noqa: E402
from hotspot_preflight.surface import enumerate_patches  # noqa: E402
from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa  # noqa: E402

# ---------------------------------------------------------------- constants

# Verbatim from build_cache_all.py. Asserted against every cache_all context's
# `feature_names` in phase `feats`, so a drift between this list and the one the
# models were trained on is a hard failure rather than a silent re-ordering.
AA = ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE', 'LEU',
      'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL', 'UNK']
BASE = ['exposure', 'concavity', 'hydrophobicity', 'connectivity']
FEATURES = BASE + ['relative_sasa', 'log_target_residues'] + ['aa_' + x for x in AA] \
    + ['charge', 'aromatic', 'polar']
for _radius in (6, 10, 14):
    FEATURES += [f'r{_radius}_{x}' for x in
                 ['log_neighbors', 'surface_fraction', 'mean_exposure',
                  'hydrophobic_fraction', 'mean_charge', 'anisotropy', 'planarity']]

AA_START = len(BASE) + 2            # first aa_* column
RELSASA_COL = len(BASE)             # 'relative_sasa'

# The pre-registered full-scale winner on cache_all/geom:
# cluster-macro majority-hit@3 = 0.422 +/- 0.029 against a random control of 0.248.
MODEL_CFG = {'kind': 'patch_classifier', 'depth': 6, 'combo': ['geom']}

PRIMARY_TARGETS = ['PD-L1', 'TNFa', 'TrkA', 'EGFR', 'TREM2', 'BHRF1', 'IL-7Ra']
SECONDARY_TARGETS = ['15-PGDH', 'BBF-14', 'Cas9', 'Latent GDF-8', 'Nipah-G',
                     'RBX1', 'VEGF-A']
EXCLUDED_TARGETS = ['MBP']          # 0/90; no within-target signal at any n

# A site whose residues are mostly absent from the coordinates cannot be
# scored. Dropped explicitly and listed in the receipt, never scored at
# whatever fraction happened to resolve.
MIN_RESOLVED_FRACTION = 0.5

# Identity tiers, as `nident / construct length` -- the fraction of the
# benchmark construct that is identically aligned, not HSP pident (a 20-residue
# exact match would read as 100% pident).
IDENT_TIERS = (('ge98', 0.98), ('ge90', 0.90), ('ge50', 0.50), ('ge30', 0.30))
# The tier whose clusters are removed from the clean model. Deliberately the
# broadest: TrkA's nearest train neighbour is a 46.9%-identity Trk-family Ig
# domain (5mo9), which a 0.50 cutoff would have kept in training while any
# reader would call it a homolog. Over-excluding costs 9 clusters out of 1065;
# under-excluding costs the claim.
EXCLUDE_IDENT_TIER = 0.30
RANDOM_REPS = 4000
SEED = 17

RECEIPT: list[str] = []


def log(msg: str = '') -> None:
    print(msg, flush=True)
    RECEIPT.append(msg)


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, default=float) + '\n')


# ---------------------------------------------------------------- cache index

def phase_index(args) -> None:
    """One pass over cache_all: per-instance patch purity, and per-chain sequence.

    Two things come out of the same read because the file is 436 MB compressed
    and parsing it twice is wasted wall-clock on a loaded machine:

    * the training index (cluster, split, per-patch purity) -- the labels
      sweep.build_training needs, minus the Jaccard conflict matrix, which is
      only used by the NMS metrics and costs an O(patches x residues) matmul per
      context;
    * the antigen sequences, reconstructed from the aa_* one-hot block of the
      cached features. Reconstructing rather than re-reading the mmCIFs
      guarantees the sequence belongs to exactly the residues that carry the
      split and cluster labels -- a separate read could drift.
    """
    files = sorted(CACHE_ALL.glob('*.json.gz'))
    letters = []
    for a in AA:
        info = gemmi.find_tabulated_residue(a)
        code = (info.one_letter_code.upper() if info else '').strip()
        letters.append(code if code else 'X')
    letters[AA.index('UNK')] = 'X'

    index, seqs = [], {}
    t0 = time.monotonic()
    for i, f in enumerate(files, 1):
        with gzip.open(f, 'rt') as s:
            ctx = json.load(s)
        if ctx['feature_names'] != FEATURES:
            raise ValueError(f'feature drift in {f.name}')
        if not ctx['patches']:
            continue
        disp = list(ctx['display_keys'])
        pat = [np.asarray(p['indices'], dtype=int) for p in ctx['patches']]
        sizes = np.asarray([len(p) for p in pat])
        for inst in ctx['instances']:
            pos = set(inst['epitope'])
            y = np.fromiter((d in pos for d in disp), dtype=bool, count=len(disp))
            if y.sum() != len(pos):
                raise ValueError(f'label identity lost for {inst["id"]}')
            inter = np.asarray([int(y[p].sum()) for p in pat])
            purity = (inter / sizes).astype(np.float32)
            coverage = (inter / max(1, int(y.sum()))).astype(np.float32)
            with np.errstate(divide='ignore', invalid='ignore'):
                f1 = np.nan_to_num(np.where(purity + coverage > 0,
                                            2 * purity * coverage / (purity + coverage), 0.0))
            index.append({'id': inst['id'], 'context': ctx['context_id'],
                          'split': inst['split'], 'cluster': inst['cluster'],
                          'n_patches': len(pat), 'purity': purity,
                          'coverage': coverage, 'f1': f1.astype(np.float32)})
        # per-chain sequence from the aa_* one-hot block
        feats = np.asarray(ctx['features'], dtype=np.float32)
        onehot = feats[:, AA_START:AA_START + len(AA)]
        aaidx = onehot.argmax(axis=1)
        bychain = collections.defaultdict(list)
        for key, ai in zip(ctx['keys'], aaidx):
            bychain[key.split(':')[0]].append(letters[int(ai)])
        seqs[ctx['context_id']] = {
            'pdb': ctx['pdb'], 'chains': list(ctx['chains']),
            'instances': [{'split': x['split'], 'cluster': x['cluster'], 'id': x['id']}
                          for x in ctx['instances']],
            'chain_seqs': {c: ''.join(v) for c, v in bychain.items()}}
        if i % 1000 == 0:
            log(f'  index {i}/{len(files)} contexts  {time.monotonic()-t0:.0f}s')
    with open(OUT / 'cache_index.pkl', 'wb') as fh:
        pickle.dump(index, fh, protocol=4)
    write_json(OUT / 'cache_seqs.json', seqs)
    per_split = collections.Counter(r['split'] for r in index)
    log(f'cache index: {len(index)} instances {dict(per_split)}; '
        f'{len(seqs)} contexts; {time.monotonic()-t0:.0f}s')


# ---------------------------------------------------------------- leakage

def phase_leak(args) -> None:
    """Which benchmark targets appear in the PRINCE TRAIN split, and as which clusters.

    blastp of each benchmark construct against every train-split antigen chain.
    Identity is reported as `nident / construct length`, i.e. the fraction of the
    benchmark construct that is identically aligned -- not HSP pident, which a
    20-residue exact match would push to 100%.
    """
    seqs = json.loads((OUT / 'cache_seqs.json').read_text())
    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    tc = pd.read_parquet(BENCH / 'downloads' / 'target_constructs.parquet')
    construct = {r['target']: str(r['target_chain_sequences']).split(' x')[0].strip()
                 for _, r in tc.iterrows()}
    targets = sorted(bm.target.unique())

    db = OUT / 'blast'
    db.mkdir(parents=True, exist_ok=True)
    subj = db / 'train_antigens.fasta'
    rec = 0
    with subj.open('w') as fh:
        for cid, d in seqs.items():
            splits = {i['split'] for i in d['instances']}
            if 'train' not in splits:
                continue
            for ch, s in d['chain_seqs'].items():
                if len(s) < 20:
                    continue
                fh.write(f'>{cid}|{d["pdb"]}|{ch}\n{s}\n')
                rec += 1
    qry = db / 'constructs.fasta'
    with qry.open('w') as fh:
        for t in targets:
            fh.write(f'>{t.replace(" ", "_")}\n{construct[t]}\n')
    subprocess.run(['makeblastdb', '-in', str(subj), '-dbtype', 'prot',
                    '-out', str(db / 'traindb')], check=True,
                   stdout=subprocess.DEVNULL)
    tab = db / 'hits.tsv'
    subprocess.run(['blastp', '-query', str(qry), '-db', str(db / 'traindb'),
                    '-outfmt', '6 qseqid sseqid pident length nident qlen slen evalue bitscore',
                    '-evalue', '1e-3', '-max_target_seqs', '5000',
                    '-num_threads', '2', '-out', str(tab)], check=True)
    cols = ['q', 's', 'pident', 'length', 'nident', 'qlen', 'slen', 'evalue', 'bits']
    hits = pd.read_csv(tab, sep='\t', names=cols) if tab.stat().st_size else pd.DataFrame(columns=cols)
    hits['target'] = hits['q'].str.replace('_', ' ', regex=False)
    hits['target'] = [t if t in construct else t.replace(' ', '-') for t in hits['target']]
    fix = {t.replace('_', ' '): t for t in targets}
    hits['target'] = [fix.get(x, x) for x in hits['q'].str.replace('_', ' ', regex=False)]
    hits['ident_frac'] = hits['nident'] / hits['qlen']
    hits['context'] = hits['s'].str.split('|').str[0]
    hits['hit_pdb'] = hits['s'].str.split('|').str[1]

    # best hit per (target, context) -- several chains of one context are the
    # same protein and would otherwise triple-count
    best = hits.sort_values('ident_frac', ascending=False) \
               .drop_duplicates(['target', 'context'])

    ctx_clusters = {cid: sorted({i['cluster'] for i in d['instances']
                                 if i['split'] == 'train'})
                    for cid, d in seqs.items()}
    # PDB entries the benchmark itself considered, for an exact-entry check
    avail = pd.read_csv(BENCH / 'structure_availability_targets.csv')
    bench_pdbs = collections.defaultdict(set)
    for r in avail.itertuples():
        for col in ('best_pdb', 'best_apo_pdb', 'best_holo_pdb'):
            v = getattr(r, col, None)
            if isinstance(v, str):
                bench_pdbs[r.target].add(v.split('_')[0].upper())

    table, excluded = [], set()
    for t in targets:
        sub = best[best.target == t]
        tiers = {}
        for name, lo in IDENT_TIERS:
            s = sub[sub.ident_frac >= lo]
            cl = sorted({c for cid in s.context for c in ctx_clusters.get(cid, [])})
            tiers[name] = {'n_contexts': int(len(s)), 'clusters': cl,
                           'n_clusters': len(cl),
                           'top_pdbs': sorted(set(s.hit_pdb))[:12]}
        exact = sorted({p for p in sub.hit_pdb.str.upper().unique()
                        if p in bench_pdbs.get(t, set())})
        row = {'target': t, 'construct_len': len(construct[t]),
               'max_ident_frac': float(sub.ident_frac.max()) if len(sub) else 0.0,
               'exact_pdb_entry_in_train': exact,
               **{f'{k}_{f}': v[f] for k, v in tiers.items()
                  for f in ('n_contexts', 'n_clusters')},
               'clusters_ge90': tiers['ge90']['clusters'],
               'clusters_ge50': tiers['ge50']['clusters'],
               'clusters_ge30': tiers['ge30']['clusters'],
               'top_pdbs_ge30': tiers['ge30']['top_pdbs'],
               'best_hit_pdb': (sub.sort_values('ident_frac', ascending=False)
                                .hit_pdb.iloc[0] if len(sub) else None),
               'best_hit_pident': (float(sub.sort_values('ident_frac', ascending=False)
                                         .pident.iloc[0]) if len(sub) else None)}
        table.append(row)
        tier = next(n for n, lo in IDENT_TIERS if lo == EXCLUDE_IDENT_TIER)
        excluded |= set(tiers[tier]['clusters'])

    df = pd.DataFrame(table)
    df.to_csv(OUT / 'leakage_table.csv', index=False)
    write_json(OUT / 'leakage.json',
               {'subject_sequences': rec, 'tier_used_for_exclusion': EXCLUDE_IDENT_TIER,
                'ident_definition': 'nident / benchmark construct length',
                'tiers': {n: lo for n, lo in IDENT_TIERS},
                'excluded_clusters': sorted(excluded), 'table': table})
    log('')
    log('LEAKAGE -- benchmark targets vs the PRINCE train split')
    log(f'  {rec} train-split antigen chain sequences in the blast subject db')
    log(f"  {'target':14s} {'maxid':>6s} {'bestpdb':>8s} {'ctx98':>5s} {'ctx90':>5s} "
        f"{'ctx50':>5s} {'ctx30':>5s} {'cl90':>4s} {'cl50':>4s} {'cl30':>4s}  "
        f"exact PDB entry also in train")
    for r in table:
        log(f"  {r['target']:14s} {r['max_ident_frac']:6.3f} "
            f"{str(r['best_hit_pdb'] or '-'):>8s} {r['ge98_n_contexts']:5d} "
            f"{r['ge90_n_contexts']:5d} {r['ge50_n_contexts']:5d} {r['ge30_n_contexts']:5d} "
            f"{r['ge90_n_clusters']:4d} {r['ge50_n_clusters']:4d} {r['ge30_n_clusters']:4d}  "
            f"{','.join(r['exact_pdb_entry_in_train']) or '-'}")
    log(f'  clusters excluded from the clean model: {len(excluded)}')


# ---------------------------------------------------------------- features

def target_structure(target: str) -> Path:
    avail = pd.read_csv(BENCH / 'structure_availability_targets.csv')
    row = avail[avail.target == target].iloc[0]
    pdb = row.best_pdb
    p = BENCH / 'structures' / f'{target.replace(" ", "_")}_{pdb}_chosen_stripped.pdb'
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def build_target_features(target: str) -> dict:
    """51 residue features + every enumerated patch, on the stripped structure.

    The body of this function is build_cache_all.build()'s feature block with the
    antibody-complex plumbing removed: here every chain in the file is target, so
    the `candidate` restriction that build_cache_all applies to the declared
    antigen chains is the identity.
    """
    path = target_structure(target)
    (OUT / 'cif').mkdir(parents=True, exist_ok=True)
    cif = OUT / 'cif' / (path.stem + '.cif')
    raw = gemmi.read_structure(str(path))
    raw.setup_entities()
    raw.make_mmcif_document().write_file(str(cif))
    tg = load_target(cif)
    if len(tg.st.assemblies):
        raise ValueError('converted file declares assemblies; exposure context unclear')

    profile = compute_burial(tg.st, context='chain', focus_chain=None,
                             reference=reference_max_sasa(tg.st))
    patches = enumerate_patches(tg, profile, max_patches=None)
    components = GeometricPredictor(weights={x: 1. for x in BASE}).score_components(tg, profile)
    names, points = residue_names(tg.st), residue_points(tg.st)
    all_keys = sorted(set(points) & set(profile.relative_sasa))
    xyz = np.array([points[k] for k in all_keys])
    tree = cKDTree(xyz)
    all_index = {k: i for i, k in enumerate(all_keys)}
    exposure = np.array([profile.relative_sasa[k] for k in all_keys])
    hydro = np.array([names[k] in {'ALA', 'VAL', 'LEU', 'ILE', 'PRO', 'PHE', 'MET',
                                   'TRP', 'CYS', 'TYR'} for k in all_keys])
    charge = np.array([1. if names[k] in {'ARG', 'LYS'} else
                       -1. if names[k] in {'ASP', 'GLU'} else 0. for k in all_keys])
    keys = list(all_keys)                      # every chain here is target
    index = {k: i for i, k in enumerate(keys)}
    feats = []
    for k in keys:
        i = all_index[k]
        name = names[k] if names[k] in AA else 'UNK'
        f = [components[k][x] for x in BASE] + [float(exposure[i]), float(np.log1p(len(keys)))] \
            + [float(name == aa) for aa in AA] \
            + [float(charge[i]), float(name in {'PHE', 'TYR', 'TRP'}),
               float(name in {'SER', 'THR', 'ASN', 'GLN'})]
        for radius in (6, 10, 14):
            ns = [j for j in tree.query_ball_point(xyz[i], radius) if j != i]
            if ns:
                cloud = xyz[ns] - xyz[i]
                eig = np.linalg.eigvalsh(cloud.T @ cloud / max(1, len(ns)))
                f += [float(np.log1p(len(ns))), float(np.mean(exposure[ns] >= .2)),
                      float(np.mean(np.minimum(exposure[ns], 1))), float(np.mean(hydro[ns])),
                      float(np.mean(charge[ns])),
                      float((eig[2] - eig[0]) / max(eig[2], 1e-9)),
                      float((eig[1] - eig[0]) / max(eig[2], 1e-9))]
            else:
                f += [0.] * 7
        feats.append(f)
    matrix = np.asarray(feats, dtype=np.float32)
    if matrix.shape != (len(keys), len(FEATURES)) or not np.isfinite(matrix).all():
        raise ValueError('invalid features')

    patch_rows = []
    for p in patches:
        inds = [index[k] for k in p.residues]
        cloud = np.array([points[k] for k in p.residues])
        center = cloud.mean(axis=0)
        patch_rows.append({'indices': inds, 'area': p.area,
                           'radius_gyration': float(np.sqrt(np.mean(
                               np.sum((cloud - center) ** 2, axis=1))))})
    # patch-level matrix, packed by sweep.pack_patches so it is byte-for-byte the
    # aggregation the models were trained on
    xp = SW.pack_patches(matrix, patch_rows)
    meta = np.asarray([[len(p['indices']), p['area'], p['radius_gyration']]
                       for p in patch_rows], dtype=np.float32)
    X = np.hstack([xp, meta])

    # construct position -> (chain, author seq id), exactly as the benchmark's
    # structure_prepare() built it: difflib matching blocks between the release
    # construct and each kept chain's observed sequence
    tc = pd.read_parquet(BENCH / 'downloads' / 'target_constructs.parquet')
    con = {r['target']: str(r['target_chain_sequences']).split(' x')[0].strip()
           for _, r in tc.iterrows()}[target].upper()
    pos2res = collections.defaultdict(list)
    model = tg.st[0]
    for ch in model:
        cseq = gemmi.one_letter_code([x.name for x in ch]).upper()
        for blk in SequenceMatcher(None, con, cseq, autojunk=False).get_matching_blocks():
            for off in range(blk.size):
                res = ch[blk.b + off]
                pos2res[blk.a + off + 1].append([ch.name, int(res.seqid.num)])

    keymap = {}
    for i, k in enumerate(keys):
        keymap[(k.auth_asym_id, int(k.auth_seq_id))] = i
    coords = np.asarray([points[k] for k in keys], dtype=np.float32)
    return {'F': matrix, 'C': coords,
            'target': target, 'structure': str(path), 'structure_sha256': sha256(path),
            'n_residues': len(keys), 'n_patches': len(patch_rows),
            'chains': [c.name for c in model],
            'keys': [str(k) for k in keys],
            'keymap': {f'{c}|{n}': i for (c, n), i in keymap.items()},
            'patch_indices': [p['indices'] for p in patch_rows],
            'relative_sasa': matrix[:, RELSASA_COL].tolist(),
            'pos2res': {str(k): v for k, v in pos2res.items()},
            'construct_len': len(con),
            'X': X}


def phase_feats(args) -> None:
    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    (OUT / 'targets').mkdir(parents=True, exist_ok=True)
    log('')
    log('TARGET FEATURES (stripped structures, max_patches=None)')
    for t in sorted(bm.target.unique()):
        p = OUT / 'targets' / f'{t.replace(" ", "_")}.npz'
        j = OUT / 'targets' / f'{t.replace(" ", "_")}.json'
        if p.exists() and j.exists() and not args.force and 'F' in np.load(p).files:
            d = json.loads(j.read_text())
            log(f'  {t:14s} cached  res={d["n_residues"]:5d} patches={d["n_patches"]:5d}')
            continue
        t0 = time.monotonic()
        d = build_target_features(t)
        X, F, C = d.pop('X'), d.pop('F'), d.pop('C')
        np.savez_compressed(p, X=X, F=F, C=C)
        write_json(j, d)
        log(f'  {t:14s} res={d["n_residues"]:5d} patches={d["n_patches"]:5d} '
            f'chains={",".join(d["chains"])} cols={X.shape[1]} '
            f'({time.monotonic()-t0:.0f}s)  {Path(d["structure"]).name}')


# ---------------------------------------------------------------- training

def phase_train(args) -> None:
    with open(OUT / 'cache_index.pkl', 'rb') as fh:
        index = pickle.load(fh)
    leak = json.loads((OUT / 'leakage.json').read_text())
    bad = set(leak['excluded_clusters'])

    have = {p.stem for p in (DATA / 'patches' / 'geom').glob('*.npz')}
    train = [r for r in index if r['split'] == 'train' and r['context'] in have]
    for a, b in (('train', 'val'), ('train', 'test'), ('val', 'test')):
        ca = {r['cluster'] for r in index if r['split'] == a}
        cb = {r['cluster'] for r in index if r['split'] == b}
        if ca & cb:
            raise ValueError(f'cluster leakage between {a} and {b}')
    clean = [r for r in train if r['cluster'] not in bad]
    log('')
    log('TRAINING')
    log(f'  config {MODEL_CFG}')
    log(f'  naive: {len(train)} train interfaces, '
        f'{len({r["cluster"] for r in train})} clusters')
    log(f'  clean: {len(clean)} train interfaces, '
        f'{len({r["cluster"] for r in clean})} clusters '
        f'({len(train)-len(clean)} interfaces / '
        f'{len({r["cluster"] for r in train}) - len({r["cluster"] for r in clean})} '
        f'clusters removed for matching a benchmark target)')
    (OUT / 'models').mkdir(parents=True, exist_ok=True)
    stats_out = {}
    for name, rows in (('clean', clean), ('naive', train)):
        dest = OUT / 'models' / f'patch_classifier_d6_geom__{name}.json'
        if dest.exists() and not args.force:
            log(f'  {name}: cached {dest.name}')
            stats_out[name] = {'cached': True}
            continue
        t0 = time.monotonic()
        rng = np.random.default_rng(SW.SEED)
        Xy = SW.build_training(rows, ('geom',), rng, MODEL_CFG['kind'])
        model = SW.fit(Xy, MODEL_CFG)
        model.save_model(str(dest))
        stats_out[name] = {'interfaces': len(rows),
                           'clusters': len({r['cluster'] for r in rows}),
                           'rows': int(Xy[0].shape[0]), 'cols': int(Xy[0].shape[1]),
                           'positives': int(Xy[1].sum()), 'seconds': time.monotonic() - t0}
        log(f'  {name}: {Xy[0].shape[0]} patch rows x {Xy[0].shape[1]} cols, '
            f'{int(Xy[1].sum())} positive, {time.monotonic()-t0:.0f}s -> {dest.name}')
    write_json(OUT / 'training.json',
               {'config': MODEL_CFG, 'excluded_clusters': sorted(bad), 'models': stats_out})


# ---------------------------------------------------------------- evaluation

def site_mapping(d: dict, residues: list[int]) -> dict:
    """Map one site's construct positions onto this structure, per target copy.

    Returns the best copy (the chain whose resolved count is highest) plus the
    per-copy resolved fractions, so a dropped site can say which copy it was
    dropped on. Chain letters are collapsed the way the benchmark collapses them:
    'binds protomer A' and 'binds protomer B' are the same site, so the score is
    taken on the copy where the site is best resolved rather than averaged over
    copies that may differ in lattice context.
    """
    pos2res = d['pos2res']
    keymap = d['keymap']
    percopy = collections.defaultdict(list)
    mapped_positions = set()
    for p in residues:
        for ch, num in pos2res.get(str(p), []):
            mapped_positions.add(p)
            i = keymap.get(f'{ch}|{num}')
            if i is not None:
                percopy[ch].append((p, i))
    out = {'n_site_residues': len(residues),
           'n_mapped_to_construct_alignment': len(mapped_positions),
           'per_copy': {c: len({p for p, _ in v}) for c, v in percopy.items()}}
    if not percopy:
        out.update({'copy': None, 'indices': [], 'resolved_fraction': 0.0})
        return out
    best = max(percopy, key=lambda c: len({p for p, _ in percopy[c]}))
    out.update({'copy': best,
                'indices': sorted({i for _, i in percopy[best]}),
                'resolved_fraction': len({p for p, _ in percopy[best]}) / len(residues)})
    return out


def phase_eval(args) -> None:
    import xgboost as xgb

    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    avail = pd.read_csv(BENCH / 'structure_availability_sites.csv')
    frac_ref = dict(zip(avail.site_id, avail.frac_scoreable))
    models = {}
    for name in ('clean', 'naive'):
        m = xgb.XGBClassifier()
        m.load_model(str(OUT / 'models' / f'patch_classifier_d6_geom__{name}.json'))
        models[name] = m

    rows, dropped = [], []
    log('')
    log('SITE MAPPING AND SCORING')
    for target in sorted(bm.target.unique()):
        j = OUT / 'targets' / f'{target.replace(" ", "_")}.json'
        d = json.loads(j.read_text())
        X = np.load(OUT / 'targets' / f'{target.replace(" ", "_")}.npz')['X']
        if X.shape[0] != d['n_patches']:
            raise ValueError(f'{target}: patch count mismatch')
        preds = {name: m.predict_proba(X)[:, 1] for name, m in models.items()}
        pat = [set(p) for p in d['patch_indices']]
        relsasa = np.asarray(d['relative_sasa'])
        patch_exposure = np.asarray([float(np.mean(relsasa[list(p)])) for p in pat])

        sub = bm[bm.target == target]
        n_ok = 0
        for s in sub.itertuples():
            res = [int(x) for x in str(s.site_residues_consensus).split(';') if x]
            mp = site_mapping(d, res)
            # ASSERTION: the alignment this script rebuilds must reproduce the
            # benchmark's own per-site resolved fraction. A silent disagreement
            # would mean the site is being scored at the wrong coordinates.
            ref = frac_ref.get(s.site_id)
            agree = None if ref is None or ref != ref else abs(mp['resolved_fraction'] - ref)
            if mp['resolved_fraction'] < MIN_RESOLVED_FRACTION:
                dropped.append({'site_id': s.site_id, 'target': target,
                                'reason': 'resolved_fraction below %.2f' % MIN_RESOLVED_FRACTION,
                                'resolved_fraction': mp['resolved_fraction'],
                                'benchmark_frac_scoreable': ref,
                                'n_site_residues': len(res), 'estimable': bool(s.estimable)})
                continue
            S = set(mp['indices'])
            inter = np.asarray([len(p & S) for p in pat])
            union = np.asarray([len(p | S) for p in pat])
            jac = inter / np.maximum(union, 1)
            best = int(np.argmax(jac))
            touching = np.flatnonzero(inter > 0)
            row = {'site_id': s.site_id, 'target': target, 'n_designs': s.n_designs,
                   'n_binders': s.n_binders, 'success_rate': s.success_rate,
                   'estimable': bool(s.estimable), 'copy': mp['copy'],
                   'n_site_residues': len(res),
                   'resolved_fraction': round(mp['resolved_fraction'], 4),
                   'benchmark_frac_scoreable': ref,
                   'frac_abs_diff_vs_benchmark': agree,
                   'best_jaccard': float(jac[best]), 'best_patch': best,
                   'best_patch_size': len(pat[best]),
                   'n_patches_touching': int(len(touching)),
                   'site_mean_relsasa': float(np.mean(relsasa[mp['indices']])),
                   'best_patch_mean_relsasa': float(patch_exposure[best])}
            for name, pr in preds.items():
                row[f'score_bestjac_{name}'] = float(pr[best])
                row[f'score_meanoverlap_{name}'] = float(np.mean(pr[touching])) \
                    if len(touching) else float(pr[best])
            rows.append(row)
            n_ok += 1
        log(f'  {target:14s} {n_ok:3d} sites scored, '
            f'{sum(1 for x in dropped if x["target"]==target):2d} dropped  '
            f'(patches={d["n_patches"]}, residues={d["n_residues"]})')

    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'site_scores.csv', index=False)
    write_json(OUT / 'dropped_sites.json', dropped)

    # mapping assertion, reported not assumed
    cmp = df.dropna(subset=['frac_abs_diff_vs_benchmark'])
    log('')
    log('MAPPING ASSERTION vs the benchmark\'s own structure_availability_sites.csv')
    log(f'  {len(cmp)} sites comparable; mean |diff| in resolved fraction '
        f'{cmp.frac_abs_diff_vs_benchmark.mean():.4f}, '
        f'max {cmp.frac_abs_diff_vs_benchmark.max():.4f}, '
        f'{int((cmp.frac_abs_diff_vs_benchmark > 0.05).sum())} sites differ by > 0.05')
    worst = cmp.nlargest(5, 'frac_abs_diff_vs_benchmark')
    for w in worst.itertuples():
        log(f'    {w.site_id:14s} ours {w.resolved_fraction:.3f} vs benchmark '
            f'{w.benchmark_frac_scoreable:.3f}')
    log(f'  {len(dropped)} sites dropped for resolved fraction < {MIN_RESOLVED_FRACTION}: '
        f'{", ".join(sorted(x["site_id"] for x in dropped)) or "none"}')

    analyse(df, dropped)


def per_target_rho(df: pd.DataFrame, col: str) -> dict:
    out = {}
    for t, g in df.groupby('target'):
        if len(g) < 3 or g.success_rate.nunique() < 2 or g[col].nunique() < 2:
            out[t] = {'n': len(g), 'rho': None, 'p': None,
                      'reason': 'no variance / n<3'}
            continue
        r = stats.spearmanr(g[col], g.success_rate)
        out[t] = {'n': int(len(g)), 'rho': float(r.statistic), 'p': float(r.pvalue)}
    return out


def aggregate(rhos: dict, targets: list[str]) -> dict:
    vals = [(t, rhos[t]) for t in targets if t in rhos and rhos[t]['rho'] is not None]
    if not vals:
        return {'n_targets': 0}
    r = np.array([v['rho'] for _, v in vals])
    n = np.array([v['n'] for _, v in vals])
    pos = int((r > 0).sum())
    sign = stats.binomtest(pos, len(r), 0.5)
    # Stouffer over per-target one-sided z (H1: positive rho), weighted by sqrt(n-1)
    z = np.array([stats.norm.isf(v['p'] / 2) * np.sign(v['rho']) for _, v in vals])
    w = np.sqrt(np.maximum(n - 1, 1))
    zc = float((w * z).sum() / np.sqrt((w ** 2).sum()))
    return {'n_targets': len(r), 'mean_rho': float(r.mean()),
            'median_rho': float(np.median(r)), 'sd_rho': float(r.std(ddof=1)) if len(r) > 1 else None,
            'n_positive': pos, 'sign_test_p': float(sign.pvalue),
            'stouffer_z': zc, 'stouffer_p_two_sided': float(2 * stats.norm.sf(abs(zc))),
            'per_target': {t: v['rho'] for t, v in vals}}


def analyse(df: pd.DataFrame, dropped: list) -> None:
    est = df[df.estimable].copy()
    power = pd.read_csv(BENCH / 'power_analysis.csv')
    mdd = dict(zip(power.target, power.mdd_80pct_power))

    score_cols = [c for c in df.columns if c.startswith('score_')]
    arms = {c: per_target_rho(est, c) for c in score_cols}
    arms['exposure_site_mean_relsasa'] = per_target_rho(est, 'site_mean_relsasa')
    arms['exposure_best_patch_relsasa'] = per_target_rho(est, 'best_patch_mean_relsasa')

    # random control: uniform scores per site, same pipeline, many reps
    rng = np.random.default_rng(SEED)
    null = collections.defaultdict(list)
    groups = {t: g.success_rate.to_numpy() for t, g in est.groupby('target')}
    for _ in range(RANDOM_REPS):
        for t, y in groups.items():
            if len(y) < 3 or len(set(y)) < 2:
                continue
            null[t].append(stats.spearmanr(rng.random(len(y)), y).statistic)
    null_stats = {t: {'mean': float(np.mean(v)), 'sd': float(np.std(v)),
                      'q025': float(np.quantile(v, .025)),
                      'q975': float(np.quantile(v, .975))}
                  for t, v in null.items()}
    # null distribution of the AGGREGATE over the primary 7
    agg_null = []
    for i in range(RANDOM_REPS):
        vals = [null[t][i] for t in PRIMARY_TARGETS if t in null and i < len(null[t])]
        if vals:
            agg_null.append(float(np.mean(vals)))

    log('')
    log('=' * 78)
    log('PER-TARGET WITHIN-TARGET SPEARMAN rho  (estimable sites, n>=5 designs)')
    log('=' * 78)
    log('Detectable |rho| at 80% power: 0.38 over the primary 7 (60 estimable rows,')
    log('53 within-target df) and 0.31 over the 14 informative targets. Minimum')
    log('detectable DIFFERENCE between two sites of one target is 0.63-0.79 in')
    log('absolute success rate. THIS BENCHMARK DETECTS LARGE EFFECTS ONLY.')
    log('')
    # How many within-target site pairs does each definition fail to separate?
    # The benchmark's own sites overlap heavily (mean pairwise Jaccard 0.617) and
    # a patch holds at most 12 residues, so several sites of one target can map
    # to the SAME enumerated patch. Where they do, the score cannot rank them at
    # all, and Spearman silently averages their ranks. This is the single most
    # important caveat on everything below, so it is measured, not assumed.
    ties = {}
    for col in score_cols + ['site_mean_relsasa', 'best_patch_mean_relsasa']:
        tot = tied = 0
        for t, g in est.groupby('target'):
            v = g[col].to_numpy()
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    tot += 1
                    tied += int(v[i] == v[j])
        ties[col] = {'pairs': tot, 'tied': tied,
                     'tied_fraction': tied / tot if tot else None}
    per_target_ties = {}
    for t, g in est.groupby('target'):
        per_target_ties[t] = {c: int(g[c].nunique()) for c in
                              ['score_bestjac_clean', 'score_meanoverlap_clean']}
        per_target_ties[t]['n_sites'] = int(len(g))
        per_target_ties[t]['n_distinct_best_patch'] = int(g.best_patch.nunique())
        per_target_ties[t]['mean_best_jaccard'] = float(g.best_jaccard.mean())
    log('')
    log('RESOLUTION OF THE SCORE DEFINITIONS (how often two sites get one score)')
    for c, v in ties.items():
        log(f"  {c:34s} {v['tied']:4d}/{v['pairs']:4d} within-target site pairs tied "
            f"({100*v['tied_fraction']:.0f}%)")
    log(f"  {'target':14s} {'n':>3s} {'distinct patch':>15s} {'distinct J-score':>17s} "
        f"{'distinct M-score':>17s} {'mean best Jaccard':>18s}")
    for t in PRIMARY_TARGETS + SECONDARY_TARGETS + EXCLUDED_TARGETS:
        v = per_target_ties.get(t)
        if not v:
            continue
        log(f"  {t:14s} {v['n_sites']:3d} {v['n_distinct_best_patch']:15d} "
            f"{v['score_bestjac_clean']:17d} {v['score_meanoverlap_clean']:17d} "
            f"{v['mean_best_jaccard']:18.3f}")

    # Does PRINCE's score track exposure within target? If PRINCE prefers the
    # less exposed patch and exposure tracks designability, the sign of the
    # headline is an exposure sign, not a site-quality judgement.
    vs_exp = {}
    for t, g in est.groupby('target'):
        if len(g) >= 3 and g.score_bestjac_clean.nunique() > 1 and g.site_mean_relsasa.nunique() > 1:
            vs_exp[t] = float(stats.spearmanr(g.score_bestjac_clean,
                                              g.site_mean_relsasa).statistic)
    log('')
    log('MECHANISM CHECK -- within-target rho(PRINCE clean-J score, site mean relative SASA)')
    log('  ' + '  '.join(f'{t}={v:+.2f}' for t, v in sorted(vs_exp.items())))
    vv = list(vs_exp.values())
    log(f'  mean over {len(vv)} targets: {np.mean(vv):+.3f}')

    head = (f"  {'target':14s} {'n':>3s} {'MDD':>5s} {'clean-J':>8s} {'clean-M':>8s} "
            f"{'naive-J':>8s} {'expos':>8s} {'null95':>14s}")
    for label, group in (('PRIMARY (heterogeneity established)', PRIMARY_TARGETS),
                         ('SECONDARY (heterogeneity not individually significant)',
                          SECONDARY_TARGETS),
                         ('EXCLUDED from ranking', EXCLUDED_TARGETS)):
        log(f'-- {label}')
        log(head)
        for t in group:
            def cell(arm):
                v = arms[arm].get(t, {})
                r = v.get('rho')
                return f'{r:+8.3f}' if r is not None else f'{"tied/na":>8s}'
            a = arms['score_bestjac_clean'].get(t, {})
            ns = null_stats.get(t, {})
            m = mdd.get(t)
            log(f"  {t:14s} {a.get('n', 0):3d} "
                f"{(f'{m:.2f}' if m == m else '  -'):>5s} "
                f"{cell('score_bestjac_clean')} {cell('score_meanoverlap_clean')} "
                f"{cell('score_bestjac_naive')} {cell('exposure_site_mean_relsasa')} "
                f"[{ns.get('q025', float('nan')):+.2f},{ns.get('q975', float('nan')):+.2f}]")

    summary = {'arms': {}, 'random_null_per_target': null_stats,
               'random_null_primary_mean_rho': {
                   'mean': float(np.mean(agg_null)), 'sd': float(np.std(agg_null)),
                   'q025': float(np.quantile(agg_null, .025)),
                   'q975': float(np.quantile(agg_null, .975))} if agg_null else None,
               'n_random_reps': RANDOM_REPS}
    log('')
    log('AGGREGATE ACROSS TARGETS')
    for name, rhos in arms.items():
        p = aggregate(rhos, PRIMARY_TARGETS)
        s = aggregate(rhos, SECONDARY_TARGETS)
        a = aggregate(rhos, PRIMARY_TARGETS + SECONDARY_TARGETS)
        summary['arms'][name] = {'per_target': rhos, 'primary': p, 'secondary': s,
                                 'primary_plus_secondary': a}
        log(f"  {name:34s} primary: mean rho {p.get('mean_rho', float('nan')):+.3f} "
            f"({p.get('n_positive')}/{p.get('n_targets')} positive, "
            f"sign p={p.get('sign_test_p', float('nan')):.3f}, "
            f"Stouffer z={p.get('stouffer_z', float('nan')):+.2f}, "
            f"p={p.get('stouffer_p_two_sided', float('nan')):.3f})")
        log(f"  {'':34s} secondary: mean rho {s.get('mean_rho', float('nan')):+.3f} "
            f"({s.get('n_positive')}/{s.get('n_targets')} positive)")
    if agg_null:
        n = summary['random_null_primary_mean_rho']
        log(f"  {'RANDOM CONTROL (mean rho, primary 7)':34s} "
            f"{n['mean']:+.3f} +/- {n['sd']:.3f}, 95% [{n['q025']:+.3f},{n['q975']:+.3f}]")

    # wider set: all sites, not only estimable
    wide = {c: per_target_rho(df, c) for c in ('score_bestjac_clean', 'score_meanoverlap_clean')}
    summary['wider_all_sites'] = {c: {'per_target': v,
                                      'primary': aggregate(v, PRIMARY_TARGETS),
                                      'secondary': aggregate(v, SECONDARY_TARGETS)}
                                  for c, v in wide.items()}
    log('')
    log('WIDER SET (all sites, including n<5 designs -- reported, not primary)')
    for c, v in summary['wider_all_sites'].items():
        log(f"  {c:34s} primary mean rho {v['primary'].get('mean_rho', float('nan')):+.3f} "
            f"({v['primary'].get('n_positive')}/{v['primary'].get('n_targets')} positive)")

    # The cleanest cut of all: targets with NO train hit at any identity tier,
    # so no retraining argument is needed for them at all.
    leak = json.loads((OUT / 'leakage.json').read_text())
    overlap = {r['target']: r['max_ident_frac'] for r in leak['table']}
    zero = [t for t, v in overlap.items() if v < EXCLUDE_IDENT_TIER]
    zp = [t for t in PRIMARY_TARGETS if t in zero]
    log('')
    log('NO-TRAINING-OVERLAP SUBSET (max construct identity in train < '
        f'{EXCLUDE_IDENT_TIER:.2f}; no exclusion argument needed)')
    log(f'  all targets: {", ".join(sorted(zero))}')
    log(f'  of the primary 7: {", ".join(zp)}')
    summary['no_overlap_subset'] = {'targets': sorted(zero), 'primary_subset': zp}
    for name in ('score_bestjac_clean', 'score_meanoverlap_clean',
                 'exposure_site_mean_relsasa'):
        a = aggregate(arms[name], zp)
        summary['no_overlap_subset'][name] = a
        log(f"  {name:34s} mean rho {a.get('mean_rho', float('nan')):+.3f} "
            f"({a.get('n_positive')}/{a.get('n_targets')} positive of "
            f"{len(zp)} subset targets)")

    summary['score_resolution'] = {'tied_pairs': ties, 'per_target': per_target_ties}
    summary['mechanism_rho_score_vs_exposure'] = vs_exp

    # sensitivity: also require the BENCHMARK's own metadata-derived
    # frac_scoreable >= 0.5, not only our coordinate-derived fraction
    strict = est[(est.benchmark_frac_scoreable.isna()) |
                 (est.benchmark_frac_scoreable >= MIN_RESOLVED_FRACTION)]
    sarms = {c: per_target_rho(strict, c) for c in
             ('score_bestjac_clean', 'score_meanoverlap_clean')}
    summary['strict_resolved_sensitivity'] = {
        'n_sites': int(len(strict)), 'n_dropped_vs_primary': int(len(est) - len(strict)),
        **{c: {'per_target': v, 'primary': aggregate(v, PRIMARY_TARGETS),
               'secondary': aggregate(v, SECONDARY_TARGETS)} for c, v in sarms.items()}}
    log('')
    log(f'SENSITIVITY -- also requiring the benchmark\'s own frac_scoreable >= '
        f'{MIN_RESOLVED_FRACTION} ({len(est)-len(strict)} further sites dropped)')
    for c, v in sarms.items():
        p = aggregate(v, PRIMARY_TARGETS)
        log(f"  {c:34s} primary mean rho {p.get('mean_rho', float('nan')):+.3f} "
            f"({p.get('n_positive')}/{p.get('n_targets')} positive)")

    # the pooled number, computed only to show what it would have claimed
    pooled = stats.spearmanr(est.score_bestjac_clean, est.success_rate)
    tmean = est.groupby('target').success_rate.transform('mean')
    pooled_targetmean = stats.spearmanr(tmean, est.success_rate)
    summary['pooled_invalid'] = {
        'rho': float(pooled.statistic), 'p': float(pooled.pvalue),
        'target_mean_only_rho': float(pooled_targetmean.statistic),
        'note': 'pooled scoring of this benchmark is invalid; shown only because a '
                'target-mean-only predictor scores rho=%.3f on the same rows'
                % pooled_targetmean.statistic}
    log('')
    log(f"POOLED (INVALID, shown for contrast): rho = {pooled.statistic:+.3f}; a "
        f"predictor emitting only its target's mean rate scores "
        f"{pooled_targetmean.statistic:+.3f} on the same rows.")

    summary['n_sites_scored'] = int(len(df))
    summary['n_estimable_scored'] = int(len(est))
    summary['n_dropped'] = len(dropped)
    write_json(OUT / 'results.json', summary)


# ---------------------------------------------------------------- LOTO on designability

# Site-level feature names: mean|max|std of the 51 residue features over the
# site's resolved residues, plus [n_resolved, radius_of_gyration].
SITE_FEATURES = ([f'mean_{x}' for x in FEATURES] + [f'max_{x}' for x in FEATURES]
                 + [f'std_{x}' for x in FEATURES] + ['n_resolved', 'radius_gyration'])
# `log_target_residues` is constant within a target, so at site level it is a
# pure target-identity channel. Under LOTO it takes an unseen value on the held
# -out target and can only waste capacity, so all three of its aggregates go.
DROP_FEATURES = {'mean_log_target_residues', 'max_log_target_residues',
                 'std_log_target_residues'}
K8 = ['mean_relative_sasa', 'mean_concavity', 'mean_hydrophobicity',
      'mean_connectivity', 'mean_exposure', 'mean_r10_mean_exposure',
      'mean_r10_planarity', 'mean_r10_hydrophobic_fraction']


def build_site_features() -> pd.DataFrame:
    """One row per scored site: the 51 residue features aggregated over the site."""
    scored = pd.read_csv(OUT / 'site_scores.csv')
    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    cons = dict(zip(bm.site_id, bm.site_residues_consensus))
    rows = []
    for target, g in scored.groupby('target'):
        stem = target.replace(' ', '_')
        d = json.loads((OUT / 'targets' / f'{stem}.json').read_text())
        with np.load(OUT / 'targets' / f'{stem}.npz') as z:
            F, C = z['F'], z['C']
        for r in g.itertuples():
            res = [int(x) for x in str(cons[r.site_id]).split(';') if x]
            mp = site_mapping(d, res)
            ix = np.asarray(mp['indices'], dtype=int)
            if not len(ix):
                raise ValueError(f'{r.site_id}: no resolved residues after scoring')
            sub = F[ix]
            cloud = C[ix]
            rg = float(np.sqrt(np.mean(np.sum((cloud - cloud.mean(0)) ** 2, axis=1))))
            vec = np.concatenate([sub.mean(0), sub.max(0), sub.std(0), [len(ix), rg]])
            rows.append({'site_id': r.site_id, 'target': target,
                         'success_rate': r.success_rate, 'n_designs': int(r.n_designs),
                         'n_binders': int(r.n_binders), 'estimable': bool(r.estimable),
                         **dict(zip(SITE_FEATURES, vec.astype(float)))})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'site_features.csv', index=False)
    return df


def expand(df: pd.DataFrame, cols: list[str]):
    """Design-level rows: the exact binomial likelihood for binders/designs.

    A site with 20 designs contributes 20 rows and a site with 5 contributes 5,
    so evidence is weighted by how much of it there is rather than every site
    counting once.
    """
    X, Y = [], []
    for _, r in df.iterrows():
        n, k = int(r.n_designs), int(r.n_binders)
        X.append(np.repeat(r[cols].to_numpy(dtype=float)[None, :], n, axis=0))
        Y.append(np.concatenate([np.ones(k), np.zeros(n - k)]))
    return np.vstack(X), np.concatenate(Y)


def fit_arm(arm: str, tr: pd.DataFrame, te: pd.DataFrame, cols: list[str]) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    Xtr, Ytr = expand(tr, cols)
    Xte = te[cols].to_numpy(dtype=float)
    if Ytr.min() == Ytr.max():
        return np.full(len(te), 0.5)
    sc = StandardScaler().fit(Xtr)            # training folds only
    Xtr, Xte = sc.transform(Xtr), sc.transform(Xte)
    if arm == 'tree_d2':
        from xgboost import XGBClassifier
        m = XGBClassifier(max_depth=2, n_estimators=50, learning_rate=0.1,
                          reg_lambda=10, min_child_weight=10, subsample=0.8,
                          random_state=SEED, n_jobs=2, tree_method='hist',
                          objective='binary:logistic', eval_metric='logloss')
    else:
        m = LogisticRegression(C=1.0, penalty='l2', max_iter=2000)
    m.fit(Xtr, Ytr)
    return m.predict_proba(Xte)[:, 1]


def loto_scores(df: pd.DataFrame, arm: str, cols: list[str],
                centered: bool = False) -> pd.DataFrame:
    """Strict leave-one-TARGET-out. Never a random split."""
    out = []
    for target in sorted(df.target.unique()):
        tr = df[df.target != target].copy()
        te = df[df.target == target].copy()
        c = list(cols)
        if centered:
            tr[c] = tr.groupby('target')[c].transform(lambda v: v - v.mean())
            te[c] = te[c] - te[c].mean()
        te = te.assign(pred=fit_arm(arm, tr, te, c))
        out.append(te[['site_id', 'target', 'success_rate', 'n_designs', 'pred']])
    return pd.concat(out, ignore_index=True)


def phase_loto(args) -> None:
    decl = OUT / 'predeclaration.json'
    log('')
    log('=' * 78)
    log('LOTO ON DESIGNABILITY LABELS')
    log('=' * 78)
    log(f'pre-declaration: {decl.name} sha256 {sha256(decl)}')
    d = json.loads(decl.read_text())
    log(f"  primary arm    : {d['primary_arm']} ({len(d['primary_arm_spec']['features'])} features, "
        f"C=1.0 fixed a priori)")
    log(f"  primary metric : {d['primary_metric'][:72]}...")
    log(f"  everything else is EXPLORATORY: {', '.join(d['exploratory_arms'])}")
    log(f"  {d['power_ceiling_restated']}")

    feat = build_site_features()
    full = [c for c in SITE_FEATURES if c not in DROP_FEATURES]
    est = feat[feat.estimable].reset_index(drop=True)
    log('')
    log(f'  {len(feat)} sites with features, {len(est)} estimable, '
        f'{est.target.nunique()} targets, {int(est.n_designs.sum())} designs')
    log(f'  site feature vector: {len(SITE_FEATURES)} cols, {len(full)} after dropping '
        f'{sorted(DROP_FEATURES)}')

    arms = {}
    specs = [('logit_k8', 'logit', K8, False), ('tree_d2', 'tree_d2', K8, False),
             ('logit_full', 'logit', full, False),
             ('logit_k8_within_target_centered', 'logit', K8, True)]
    for name, arm, cols, cen in specs:
        t0 = time.monotonic()
        pred = loto_scores(est, arm, cols, centered=cen)
        pred.to_csv(OUT / f'loto_pred__{name}.csv', index=False)
        arms[name] = per_target_rho(pred.rename(columns={'pred': 'score'}), 'score')
        log(f'  fitted {name:34s} ({time.monotonic()-t0:.0f}s)')
    # unfitted baseline, sign fixed positive a priori
    base = est.assign(score=est.mean_relative_sasa)
    arms['exposure_alone_unfitted'] = per_target_rho(base, 'score')

    rng = np.random.default_rng(SEED)
    groups = {t: g.success_rate.to_numpy() for t, g in est.groupby('target')}
    null = collections.defaultdict(list)
    for _ in range(RANDOM_REPS):
        for t, y in groups.items():
            if len(y) >= 3 and len(set(y)) > 1:
                null[t].append(stats.spearmanr(rng.random(len(y)), y).statistic)
    agg_null = [float(np.mean([null[t][i] for t in PRIMARY_TARGETS
                               if t in null and i < len(null[t])]))
                for i in range(RANDOM_REPS)]

    log('')
    log('PER-TARGET HELD-OUT rho (estimable sites; the target was never in training)')
    cols_order = ['exposure_alone_unfitted', 'logit_k8', 'tree_d2', 'logit_full',
                  'logit_k8_within_target_centered']
    log(f"  {'target':14s} {'n':>3s} " + ' '.join(f'{c[:12]:>13s}' for c in cols_order))
    for grp, label in ((PRIMARY_TARGETS, 'PRIMARY'), (SECONDARY_TARGETS, 'SECONDARY'),
                       (EXCLUDED_TARGETS, 'EXCLUDED')):
        log(f'-- {label}')
        for t in grp:
            n = arms['logit_k8'].get(t, {}).get('n', 0)
            cells = []
            for c in cols_order:
                r = arms[c].get(t, {}).get('rho')
                cells.append(f'{r:+13.3f}' if r is not None else f'{"tied/na":>13s}')
            log(f'  {t:14s} {n:3d} ' + ' '.join(cells))

    log('')
    log('AGGREGATE (mean per-target held-out rho)')
    summary = {'predeclaration_sha256': sha256(decl), 'arms': {}}
    for c in cols_order:
        pr = aggregate(arms[c], PRIMARY_TARGETS)
        se = aggregate(arms[c], SECONDARY_TARGETS)
        # bootstrap over TARGETS, which is the unit that generalises
        vals = [arms[c][t]['rho'] for t in PRIMARY_TARGETS
                if t in arms[c] and arms[c][t]['rho'] is not None]
        bs = [float(np.mean(rng.choice(vals, size=len(vals), replace=True)))
              for _ in range(10000)] if vals else []
        ci = [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))] if bs else None
        summary['arms'][c] = {'per_target': arms[c], 'primary': pr, 'secondary': se,
                              'bootstrap_ci95_over_targets': ci}
        flag = 'PRIMARY ARM' if c == 'logit_k8' else (
            'BASELINE' if c.startswith('exposure') else 'exploratory')
        log(f"  {c:34s} {pr.get('mean_rho', float('nan')):+.3f} "
            f"({pr.get('n_positive')}/{pr.get('n_targets')} positive, sign p="
            f"{pr.get('sign_test_p', float('nan')):.3f}, Stouffer p="
            f"{pr.get('stouffer_p_two_sided', float('nan')):.3f}, "
            f"boot95 [{ci[0]:+.3f},{ci[1]:+.3f}])  [{flag}]" if ci else f'  {c}: n/a')
        log(f"  {'':34s} secondary {se.get('mean_rho', float('nan')):+.3f} "
            f"({se.get('n_positive')}/{se.get('n_targets')} positive)")
    nn = {'mean': float(np.mean(agg_null)), 'sd': float(np.std(agg_null)),
          'q025': float(np.quantile(agg_null, .025)),
          'q975': float(np.quantile(agg_null, .975))}
    summary['random_null_primary_mean_rho'] = nn
    log(f"  {'RANDOM CONTROL':34s} {nn['mean']:+.3f} +/- {nn['sd']:.3f}, "
        f"95% [{nn['q025']:+.3f},{nn['q975']:+.3f}]")

    # label-shuffle control: does the pipeline manufacture signal?
    log('')
    log('LABEL-SHUFFLE CONTROL (primary arm; binders permuted across sites '
        'within target in every training fold)')
    sh = []
    for rep in range(args.shuffle_reps):
        # Permute each site's measured RATE among the sites of its own target,
        # then rebuild the binder count against that site's own n_designs. This
        # destroys the site->outcome link while leaving every site's amount of
        # evidence, and the whole target structure, untouched.
        shuf = est.copy()
        rate = shuf.success_rate.to_numpy().copy()
        for t, g in est.groupby('target'):
            ix = g.index.to_numpy()
            rate[ix] = rng.permutation(rate[ix])
        shuf['success_rate'] = rate
        shuf['n_binders'] = np.clip(np.rint(rate * shuf.n_designs.to_numpy()), 0,
                                    shuf.n_designs.to_numpy()).astype(int)
        pred = loto_scores(shuf, 'logit', K8)
        r = per_target_rho(pred.rename(columns={'pred': 'score'}), 'score')
        v = [r[t]['rho'] for t in PRIMARY_TARGETS if t in r and r[t]['rho'] is not None]
        if v:
            sh.append(float(np.mean(v)))
    summary['label_shuffle_control'] = {
        'reps': len(sh), 'mean': float(np.mean(sh)), 'sd': float(np.std(sh)),
        'q025': float(np.quantile(sh, .025)), 'q975': float(np.quantile(sh, .975))} if sh else None
    if sh:
        log(f'  {len(sh)} reps: mean rho {np.mean(sh):+.3f} +/- {np.std(sh):.3f}, '
            f'95% [{np.quantile(sh,.025):+.3f},{np.quantile(sh,.975):+.3f}]')

    # wider set
    wide = feat.reset_index(drop=True)
    wp = loto_scores(wide, 'logit', K8)
    wr = per_target_rho(wp.rename(columns={'pred': 'score'}), 'score')
    summary['wider_all_sites'] = {'logit_k8': {'per_target': wr,
                                               'primary': aggregate(wr, PRIMARY_TARGETS),
                                               'secondary': aggregate(wr, SECONDARY_TARGETS)}}
    log('')
    log('WIDER SET (all sites incl. n<5 designs -- reported, not primary)')
    log(f"  logit_k8 primary mean rho "
        f"{summary['wider_all_sites']['logit_k8']['primary'].get('mean_rho', float('nan')):+.3f} "
        f"({summary['wider_all_sites']['logit_k8']['primary'].get('n_positive')}/"
        f"{summary['wider_all_sites']['logit_k8']['primary'].get('n_targets')} positive)")

    # DIAGNOSTIC on the pre-declared primary arm (not a new arm): can it fit the
    # data it was trained on? If in-sample rho is high and held-out rho is zero,
    # the features carry target-specific signal that does not transfer. If
    # in-sample rho is ALSO near zero, these features simply do not encode
    # designability and no amount of held-out care would have helped.
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    Xa, Ya = expand(est, K8)
    sc = StandardScaler().fit(Xa)
    m = LogisticRegression(C=1.0, penalty='l2', max_iter=2000).fit(sc.transform(Xa), Ya)
    insample = est.assign(score=m.predict_proba(sc.transform(est[K8].to_numpy(dtype=float)))[:, 1])
    ins = per_target_rho(insample, 'score')
    iv = [ins[t]['rho'] for t in PRIMARY_TARGETS if t in ins and ins[t]['rho'] is not None]
    coefs = dict(zip(K8, [float(x) for x in m.coef_[0]]))
    summary['primary_arm_diagnostic'] = {
        'in_sample_mean_rho_primary7': float(np.mean(iv)),
        'in_sample_per_target': {t: ins[t]['rho'] for t in PRIMARY_TARGETS if t in ins},
        'held_out_mean_rho_primary7': summary['arms']['logit_k8']['primary'].get('mean_rho'),
        'coefficients_refit_on_all_estimable': coefs,
        'note': 'coefficients are on standardised features; refit on all estimable sites '
                'for interpretation only, never used for any reported rho'}
    log('')
    log('PRIMARY-ARM DIAGNOSTIC -- can logit_k8 fit the data it trained on?')
    log(f'  in-sample  mean per-target rho (primary 7): {np.mean(iv):+.3f}')
    log(f"  held-out   mean per-target rho (primary 7): "
        f"{summary['arms']['logit_k8']['primary'].get('mean_rho'):+.3f}")
    log('  coefficients (standardised, refit on all estimable sites, interpretation only):')
    for k, v in sorted(coefs.items(), key=lambda kv: -abs(kv[1])):
        log(f'    {k:36s} {v:+.3f}')

    # the sign-flip, quantified
    prev = json.loads((OUT / 'results.json').read_text())
    ab = json.loads((DATA / 'metric_f1.json').read_text())
    expo = ab['arms']['exposure']
    sign = {'antibody_epitopes': {
                'metric': ab['metric'], 'arm': 'exposure',
                'f1_at10': expo['f1']['10'],
                'random_mean': ab['random']['f1']['10']['mean'],
                'random_sd': ab['random']['f1']['10']['sd'],
                'z_at10': expo['f1_vs_random']['10']['z'],
                'p_random_ge_at10': expo['f1_vs_random']['10']['p_random_ge'],
                'z_at5': expo['f1_vs_random']['5']['z'],
                'z_at3': expo['f1_vs_random']['3']['z'],
                'n_test_interfaces': ab['n_test_interfaces'],
                'n_test_clusters': ab['n_test_clusters'],
                'oracle_f1': ab['oracle']['f1'],
                'direction': 'ANTI-predictive'},
            'minibinder_designability': {
                'metric': 'mean per-target within-target Spearman rho vs measured success_rate',
                'mean_rho_primary7': summary['arms']['exposure_alone_unfitted']['primary']
                                     .get('mean_rho'),
                'n_positive': summary['arms']['exposure_alone_unfitted']['primary']
                              .get('n_positive'),
                'n_targets': summary['arms']['exposure_alone_unfitted']['primary']
                             .get('n_targets'),
                'bootstrap_ci95_over_targets':
                    summary['arms']['exposure_alone_unfitted']['bootstrap_ci95_over_targets'],
                'stouffer_p': summary['arms']['exposure_alone_unfitted']['primary']
                              .get('stouffer_p_two_sided'),
                'random_null_95': [nn['q025'], nn['q975']],
                'direction': 'weakly POSITIVE, not individually significant'}}
    summary['sign_flip'] = sign
    log('')
    log('=' * 78)
    log('THE SIGN FLIP, QUANTIFIED')
    log('=' * 78)
    a = sign['antibody_epitopes']
    m = sign['minibinder_designability']
    log(f"  antibody epitopes    exposure F1@10 {a['f1_at10']:.4f} vs random "
        f"{a['random_mean']:.4f}+/-{a['random_sd']:.4f}  z={a['z_at10']:+.2f}  "
        f"p(random>=obs)={a['p_random_ge_at10']}")
    log(f"                       z@3={a['z_at3']:+.2f} z@5={a['z_at5']:+.2f} -> monotone in k; "
        f"{a['n_test_interfaces']} interfaces / {a['n_test_clusters']} clusters; "
        f"oracle F1 ceiling {a['oracle_f1']:.4f}")
    log(f"  designability        exposure mean per-target rho "
        f"{m['mean_rho_primary7']:+.3f} ({m['n_positive']}/{m['n_targets']} targets positive)"
        f"  boot95 [{m['bootstrap_ci95_over_targets'][0]:+.3f},"
        f"{m['bootstrap_ci95_over_targets'][1]:+.3f}]  Stouffer p={m['stouffer_p']:.3f}")
    log(f"                       random null 95% [{nn['q025']:+.3f},{nn['q975']:+.3f}] -- the "
        f"designability estimate is INSIDE it")
    write_json(OUT / 'loto_results.json', summary)


# ---------------------------------------------------------------- receipt

def phase_receipt(args) -> None:
    inputs = {}
    for p in [BENCH / 'site_benchmark.csv', BENCH / 'RECEIPT.txt',
              BENCH / 'RECEIPT_structures.txt', BENCH / 'power_analysis.csv',
              BENCH / 'structure_availability_sites.csv',
              BENCH / 'structure_availability_targets.csv',
              BENCH / 'structure_sasa_sites.csv',
              BENCH / 'downloads' / 'target_constructs.parquet',
              HERE / 'sweep.py', HERE / 'build_cache_all.py',
              CODE / 'src/hotspot_preflight/surface.py',
              CODE / 'src/hotspot_preflight/checks/sasa.py',
              CODE / 'src/hotspot_preflight/predict/features.py',
              DATA / 'cv_results__cache_all__geom.json']:
        if Path(p).exists():
            inputs[str(p)] = sha256(p)
    for p in sorted((BENCH / 'structures').glob('*_chosen_stripped.pdb')):
        inputs[str(p)] = sha256(p)
    inputs[str(Path(__file__).resolve())] = sha256(__file__)
    write_json(OUT / 'input_sha256.json', inputs)
    log('')
    log('=' * 78)
    log('RECEIPT')
    log('=' * 78)
    log(f'script sha256: {sha256(__file__)}')
    log(f'inputs hashed: {len(inputs)} files -> input_sha256.json')
    log('score definitions:')
    log('  bestjac     -- the enumerated patch with the highest Jaccard against the')
    log('                 site residue set (primary definition)')
    log('  meanoverlap -- mean score of every enumerated patch sharing >=1 residue')
    log('                 with the site (sensitivity arm)')
    log('  both are reported for both models; neither was chosen after seeing results')
    log('controls: uniform-random per-site scores (%d reps) and exposure alone'
        % RANDOM_REPS)
    (OUT / 'RECEIPT_site_scoring.txt').write_text('\n'.join(RECEIPT) + '\n')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', required=True,
                    choices=['index', 'leak', 'feats', 'train', 'eval', 'loto',
                             'receipt', 'all'])
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--shuffle-reps', type=int, default=100)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    order = ['index', 'leak', 'feats', 'train', 'eval', 'loto', 'receipt']
    todo = order if args.phase == 'all' else [args.phase]
    fns = {'index': phase_index, 'leak': phase_leak, 'feats': phase_feats,
           'train': phase_train, 'eval': phase_eval, 'loto': phase_loto,
           'receipt': phase_receipt}
    for ph in todo:
        log(f'### phase {ph}  {time.strftime("%Y-%m-%dT%H:%M:%S")}')
        fns[ph](args)
    if args.phase != 'receipt':
        prev = (OUT / 'RECEIPT_site_scoring.txt')
        prev.write_text((prev.read_text() if prev.exists() and args.phase != 'all' else '')
                        + '\n'.join(RECEIPT) + '\n')


if __name__ == '__main__':
    main()
