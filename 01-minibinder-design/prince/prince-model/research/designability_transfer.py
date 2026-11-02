"""Transfer the CV-LOCKED PRINCE model onto the minibinder-designability benchmark.

`score_site_benchmark.py` already asked this question, but with a stand-in:
`patch_classifier_d6_geom` -- geometry only. The model actually locked by
`sweep.py --phase lock` is `patch_classifier_d6_geom+atom+esm` (sweep_lock.json),
whose cluster-macro majority-hit@3 is 0.511 +/- 0.033 against a random control of
0.247 -- substantially stronger on its own task than the geom-only arm. So the
earlier null could have been a null about a weaker model rather than about the
method. This script closes that gap: it rebuilds the locked model's EXACT feature
stack on the 15 benchmark target structures, applies the locked model, and
re-measures.

What is reused verbatim rather than reimplemented:

* geometry  -- `build_cache_all.build()`'s feature block, same `FEATURES` order,
               same `compute_burial(context='chain', focus_chain=None)`, same
               `enumerate_patches(..., max_patches=None)`. Asserted equal, bit for
               bit, to the 51-feature matrix `score_site_benchmark.py` already
               wrote for these same structures.
* atom      -- `build_atom_features.build_one`, called in-process (the `--workers 1`
               path) with `CIF_DIR` pointed at a symlink tree of the stripped
               structures. The file itself is untouched.
* esm       -- `build_esm.build_one` / `chain_sequences` / `embed`, same model and
               revision, and the **already-fitted** PCA from
               `esm_pca__t30_150M__cache_all__4457ctx.json` (pca_id 57d5bd1fce5fedbc).
               Never refitted: refitting on 15 targets would change the basis the
               model was trained in.
* packing   -- `sweep.phase_pack` with `sweep.HERE` redirected to this script's own
               output tree, so nothing is written into the shared `patches/`.
* training  -- `sweep.load_index` / `sweep.build_training` / `sweep.fit` on
               `cache_all`, exactly as `sweep.phase_test` and `residue_h2h.py` do.
* scoring   -- the two score definitions and the within-target evaluation of
               `score_site_benchmark.py`, so the numbers are comparable to the
               geom-only run they replace.

Evaluation rules are the benchmark's own and are enforced, not advised: within-target
Spearman only (a predictor emitting its target's mean success rate scores pooled
rho = 0.750, which is target recognition), estimable sites only, macro-average over
the primary 7, random control, and an explicit tie/degeneracy measurement.

Run with the research environment described in docs/reproducibility.md. Phases are independent and resumable:
  cache -> atom -> esm -> pack -> train -> eval -> receipt   (or --phase all)
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import collections
import gzip
import hashlib
import json
import os
import sys
import time
from argparse import Namespace
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path

# transformers probes TensorFlow at import and the installed TF is AVX-built on a
# machine without AVX -- the probe hard-crashes the interpreter. Set before any
# transformers import can happen, including the one inside build_esm.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
ROOT = REPO
BENCH = (DATA / "site_benchmark")
REF = (DATA / "site_scoring")        # READ-ONLY
CACHE_ALL = (DATA / "cache_all")     # READ-ONLY
SHARED_PATCHES = DATA / 'patches'                           # READ-ONLY
OUT = (DATA / "designability_transfer")

sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
sys.path.insert(0, str(HERE))

import gemmi  # noqa: E402

from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa  # noqa: E402
from hotspot_preflight.predict.features import residue_names, residue_points  # noqa: E402
from hotspot_preflight.predict.geometric import GeometricPredictor  # noqa: E402
from hotspot_preflight.structure import load_target  # noqa: E402
from hotspot_preflight.surface import enumerate_patches  # noqa: E402

# ---------------------------------------------------------------- constants

# Verbatim from build_cache_all.py. Asserted against the cached `feature_names`
# of a cache_all context before anything is scored, so drift is a hard failure.
AA = ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE', 'LEU',
      'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL', 'UNK']
BASE = ['exposure', 'concavity', 'hydrophobicity', 'connectivity']
FEATURES = BASE + ['relative_sasa', 'log_target_residues'] + ['aa_' + x for x in AA] \
    + ['charge', 'aromatic', 'polar']
for _radius in (6, 10, 14):
    FEATURES += [f'r{_radius}_{x}' for x in
                 ['log_neighbors', 'surface_fraction', 'mean_exposure',
                  'hydrophobic_fraction', 'mean_charge', 'anisotropy', 'planarity']]

RELSASA_COL = len(BASE)

CACHE_VERSION = 'all_declared_antigen_chains_v2'   # build_cache_all's own tag

PCA_PATH = DATA / 'esm_pca__t30_150M__cache_all__4457ctx.json'
PCA_ID = '57d5bd1fce5fedbc'
ESM_MODEL = 'facebook/esm2_t30_150M_UR50D'
ESM_REVISION = 'a695f6045e2e32885fa60af20c13cb35398ce30c'

LOCK_PATH = DATA / 'sweep_lock.json'
COMBO = ('geom', 'atom', 'esm')

PRIMARY_TARGETS = ['PD-L1', 'TNFa', 'TrkA', 'EGFR', 'TREM2', 'BHRF1', 'IL-7Ra']
SECONDARY_TARGETS = ['15-PGDH', 'BBF-14', 'Cas9', 'Latent GDF-8', 'Nipah-G',
                     'RBX1', 'VEGF-A']
EXCLUDED_TARGETS = ['MBP']
NO_OVERLAP_SUBSET = ['TREM2', 'BHRF1', 'IL-7Ra']

MIN_RESOLVED_FRACTION = 0.5
RANDOM_REPS = 4000
SEED = 17

RECEIPT: list[str] = []

# sklearn/xgboost (pulled in by sweep) and torch each ship their own libomp, and
# loading both in one interpreter segfaults this machine whichever way round they
# go: sklearn-then-torch kills the ESM2 forward pass, torch-then-sklearn kills the
# XGBoost fit (both SIGSEGV / exit 139; pandas, scipy and freesasa are innocent).
# So neither is imported at module scope. The `esm` phase imports torch and never
# touches sweep; every other phase calls `load_sweep()` and never imports torch;
# `--phase all` runs each phase as its own subprocess so the two never meet.
SW = None


def load_sweep():
    """Import sweep lazily. See the libomp note above."""
    global SW
    if SW is None:
        import sweep
        SW = sweep
    return SW


def log(msg: str = '') -> None:
    print(msg, flush=True)
    RECEIPT.append(msg)


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, default=float) + '\n')


def slug(target: str) -> str:
    return target.replace(' ', '_')


def keystr(k) -> str:
    """build_cache_all.keystr, verbatim (including the truthy-space icode quirk)."""
    return f'{k.auth_asym_id}:{k.auth_seq_id}' + (f':{k.icode}' if k.icode else '')


def targets() -> list[str]:
    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    return sorted(bm.target.unique())


def context_id(target: str) -> str:
    """Deterministic, and deliberately not a 16-hex string: a cache_all context id
    must never be mistaken for one of these, nor these for one of those."""
    return 'dt_' + slug(target).lower()


def stripped_cif(target: str) -> Path:
    """The `*_chosen_stripped.cif` the site-scoring run converted from the
    benchmark's stripped PDB. Partners removed, empty cell, P 1, no assemblies."""
    hits = sorted((REF / 'cif').glob(f'{slug(target)}_*_chosen_stripped.cif'))
    if len(hits) != 1:
        raise FileNotFoundError(f'{target}: {len(hits)} stripped cifs in {REF/"cif"}')
    return hits[0]


# ---------------------------------------------------------------- phase: cache

def build_context(target: str) -> dict:
    """build_cache_all.build()'s feature block on a stripped benchmark structure.

    Differences from build(), and only these:
      * the structure is loaded from a local stripped cif rather than located in
        the RCSB mirror and reduced by load_antigen -- here every chain in the
        file is already target, so load_antigen's reduction is the identity;
      * `instances` is empty (no epitope labels exist for these targets), so the
        LabelIdentityError check has nothing to check. Every other check stays.
    """
    cif = stripped_cif(target)
    tg = load_target(cif)
    if len(tg.st.assemblies):
        raise ValueError(f'{target}: converted file declares assemblies; '
                         'exposure context unclear')
    model = tg.st[0]
    original = {c.name for c in model}

    profile = compute_burial(tg.st, context='chain', focus_chain=None,
                             reference=reference_max_sasa(tg.st))
    candidate = replace(
        profile,
        relative_sasa={k: v for k, v in profile.relative_sasa.items()
                       if k.auth_asym_id in original},
        absolute_sasa={k: v for k, v in profile.absolute_sasa.items()
                       if k.auth_asym_id in original})
    patches = enumerate_patches(tg, candidate, max_patches=None)
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
    keys = [k for k in all_keys if k.auth_asym_id in original]
    index = {k: i for i, k in enumerate(keys)}
    feats = []
    for k in keys:
        i = all_index[k]
        name = names[k] if names[k] in AA else 'UNK'
        f = [components[k][x] for x in BASE] \
            + [float(exposure[i]), float(np.log1p(len(keys)))] \
            + [float(name == aa) for aa in AA] \
            + [float(charge[i]), float(name in {'PHE', 'TYR', 'TRP'}),
               float(name in {'SER', 'THR', 'ASN', 'GLN'})]
        for radius in (6, 10, 14):
            ns = [j for j in tree.query_ball_point(xyz[i], radius) if j != i]
            if ns:
                cloud = xyz[ns] - xyz[i]
                eig = np.linalg.eigvalsh(cloud.T @ cloud / max(1, len(ns)))
                f += [float(np.log1p(len(ns))), float(np.mean(exposure[ns] >= .2)),
                      float(np.mean(np.minimum(exposure[ns], 1))),
                      float(np.mean(hydro[ns])), float(np.mean(charge[ns])),
                      float((eig[2] - eig[0]) / max(eig[2], 1e-9)),
                      float((eig[1] - eig[0]) / max(eig[2], 1e-9))]
            else:
                f += [0.] * 7
        feats.append(f)
    matrix = np.asarray(feats)
    if matrix.shape != (len(keys), len(FEATURES)) or not np.isfinite(matrix).all():
        raise ValueError(f'{target}: invalid features')

    patch_rows = []
    for p in patches:
        inds = [index[k] for k in p.residues]
        cloud = np.array([points[k] for k in p.residues])
        center = cloud.mean(axis=0)
        patch_rows.append({'indices': inds, 'area': p.area,
                           'radius_gyration': float(np.sqrt(np.mean(
                               np.sum((cloud - center) ** 2, axis=1))))})
    display = [str(k) for k in keys]
    if len(set(display)) != len(display):
        raise ValueError(f'{target}: ambiguous display residue identities')

    # construct position -> (chain, author seq id), rebuilt exactly as the
    # benchmark's structure_prepare() and score_site_benchmark.py build it.
    tc = pd.read_parquet(BENCH / 'downloads' / 'target_constructs.parquet')
    con = {r['target']: str(r['target_chain_sequences']).split(' x')[0].strip()
           for _, r in tc.iterrows()}[target].upper()
    pos2res = collections.defaultdict(list)
    for ch in model:
        cseq = gemmi.one_letter_code([x.name for x in ch]).upper()
        for blk in SequenceMatcher(None, con, cseq, autojunk=False).get_matching_blocks():
            for off in range(blk.size):
                res = ch[blk.b + off]
                pos2res[blk.a + off + 1].append([ch.name, int(res.seqid.num)])

    return {
        'cache_version': CACHE_VERSION, 'context_id': context_id(target),
        'pdb': None,  # filled by the caller with the symlink id
        'chains': sorted(original), 'assembly_used': False,
        'coordinate_sha256': sha256(cif), 'feature_names': FEATURES,
        'keys': [keystr(k) for k in keys], 'display_keys': display,
        'coordinates': [points[k] for k in keys], 'features': feats,
        'patches': patch_rows, 'instances': [],
        # benchmark plumbing, not features
        'target': target, 'structure': str(cif),
        'n_residues': len(keys), 'n_patches': len(patch_rows),
        'keymap': {f'{k.auth_asym_id}|{int(k.auth_seq_id)}': i for i, k in enumerate(keys)},
        'patch_indices': [p['indices'] for p in patch_rows],
        'relative_sasa': np.asarray(matrix[:, RELSASA_COL], dtype=np.float32).tolist(),
        'pos2res': {str(k): v for k, v in pos2res.items()},
        'construct_len': len(con),
    }


def phase_cache(args) -> None:
    (OUT / 'cache').mkdir(parents=True, exist_ok=True)
    (OUT / 'cif').mkdir(parents=True, exist_ok=True)
    log('')
    log('PHASE cache -- 51 geom features + full patch pool on 15 stripped structures')
    sample = sorted(CACHE_ALL.glob('*.json.gz'))[0]
    with gzip.open(sample, 'rt') as s:
        if json.load(s)['feature_names'] != FEATURES:
            raise ValueError('FEATURES drift vs cache_all; the model was trained '
                             'on a different column order')
    log(f'  FEATURES ({len(FEATURES)}) asserted identical to cache_all ({sample.name})')

    pdbmap, mismatches = {}, []
    for n, t in enumerate(targets(), 1):
        cid = context_id(t)
        pdb_id = f'dt{n:02d}'
        pdbmap[t] = {'pdb_id': pdb_id, 'context_id': cid,
                     'cif': str(stripped_cif(t))}
        link = OUT / 'cif' / f'{pdb_id}.cif'
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(stripped_cif(t))

        dest = OUT / 'cache' / f'{cid}.json.gz'
        if dest.exists() and not args.force:
            with gzip.open(dest, 'rt') as s:
                d = json.load(s)
            log(f'  {t:14s} cached  res={d["n_residues"]:5d} patches={d["n_patches"]:5d}')
        else:
            t0 = time.monotonic()
            d = build_context(t)
            d['pdb'] = pdb_id
            with gzip.open(dest, 'wt') as s:
                json.dump(d, s, allow_nan=False)
            log(f'  {t:14s} res={d["n_residues"]:5d} patches={d["n_patches"]:5d} '
                f'chains={",".join(d["chains"])} ({time.monotonic()-t0:.0f}s)')

        # --- verification against the already-recorded geom artifacts ---------
        ref = json.loads((REF / 'targets' / f'{slug(t)}.json').read_text())
        refF = np.load(REF / 'targets' / f'{slug(t)}.npz')['F']
        bad = {}
        if list(ref['keys']) != list(d['display_keys']):
            bad['keys'] = {'ref': len(ref['keys']), 'ours': len(d['display_keys']),
                           'first_diff': next((i for i, (a, b) in enumerate(
                               zip(ref['keys'], d['display_keys'])) if a != b), None)}
        if list(ref['patch_indices']) != list(d['patch_indices']):
            bad['patch_indices'] = {'ref': len(ref['patch_indices']),
                                    'ours': len(d['patch_indices'])}
        ours = np.asarray(d['features'], dtype=np.float32)
        if ours.shape != refF.shape or not np.array_equal(ours, refF):
            bad['features'] = {'shape_ref': list(refF.shape), 'shape_ours': list(ours.shape),
                               'max_abs_diff': float(np.abs(ours - refF).max())
                               if ours.shape == refF.shape else None}
        if ref['keymap'] != d['keymap']:
            bad['keymap'] = True
        if {str(k): v for k, v in ref['pos2res'].items()} != d['pos2res']:
            bad['pos2res'] = True
        if bad:
            mismatches.append({'target': t, 'detail': bad})
            log(f'    MISMATCH vs site_scoring/targets/{slug(t)}: {json.dumps(bad)}')
        else:
            log(f'    verified identical to site_scoring/targets/{slug(t)}.* '
                f'(keys, patch pool, 51-feature matrix, keymap, pos2res)')

    write_json(OUT / 'pdbmap.json', pdbmap)
    if mismatches:
        write_json(OUT / 'cache_mismatches.json', mismatches)
        raise SystemExit('STOPPING: residue keys / geometry do not match the keys '
                         'already recorded in site_scoring/targets/. See '
                         f'{OUT/"cache_mismatches.json"}')
    log(f'  all 15 contexts verified against the recorded geom artifacts')


# ---------------------------------------------------------------- phase: atom

def phase_atom(args) -> None:
    import build_atom_features as AF

    names = json.loads((DATA / 'atom_feature_names.json').read_text())
    if list(AF.FEATURE_NAMES) != list(names):
        raise ValueError('atom feature order drift vs atom_feature_names.json')
    # The stripped structures are not in the RCSB mirror. Point the module's
    # locator at the symlink tree built in phase `cache`; the file is otherwise
    # untouched and build_one is the exact `--workers 1` code path.
    AF.CIF_DIR = OUT / 'cif'
    out = OUT / 'atom_cache'
    out.mkdir(parents=True, exist_ok=True)
    log('')
    log(f'PHASE atom -- {len(names)} features, build_atom_features.build_one '
        f'({AF.FEATURE_VERSION}), CIF_DIR -> {AF.CIF_DIR}')
    rows = []
    for p in sorted((OUT / 'cache').glob('*.json.gz')):
        r = AF.build_one((str(p), str(out), not args.force))
        rows.append(r)
        log(f'  {r["context"]:20s} ok={r["ok"]} res={r.get("residues","-")} '
            f'reused={r.get("reused","-")} {r["seconds"]}s {r.get("error","")}')
    ok = [r for r in rows if r['ok']]
    write_json(OUT / 'atom_receipt.json',
               {'script_sha256': sha256(HERE / 'build_atom_features.py'),
                'feature_version': AF.FEATURE_VERSION, 'n_features': AF.N_FEATURES,
                'cif_dir': str(AF.CIF_DIR), 'out_dir': str(out),
                'contexts_attempted': len(rows), 'contexts_completed': len(ok),
                'errors': [{'context': r['context'], 'error': r['error']}
                           for r in rows if not r['ok']],
                'feature_names': names})
    log(f'  {len(ok)}/{len(rows)} contexts, {AF.N_FEATURES} features')
    if len(ok) != len(rows):
        raise SystemExit('atom features incomplete')


# ---------------------------------------------------------------- phase: esm

def phase_esm(args) -> None:
    import build_esm as BE

    pca = json.loads(PCA_PATH.read_text())
    if pca['pca_id'] != PCA_ID:
        raise ValueError(f'pca_id {pca["pca_id"]!r} != locked {PCA_ID!r}')
    if pca['model'] != ESM_MODEL or pca['n_components'] != 64:
        raise ValueError('locked PCA was fitted for a different model/width')
    comps = np.asarray(pca['components'], dtype=np.float32)
    mean = np.asarray(pca['mean'], dtype=np.float32)
    if BE.projection_id(comps, mean) != PCA_ID:
        raise ValueError('reloaded PCA does not hash to its own pca_id')

    BE.CIF_DIR = OUT / 'cif'
    out = OUT / 'esm_cache'
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(BE.THREADS)

    from transformers import AutoTokenizer, EsmForMaskedLM
    tok = AutoTokenizer.from_pretrained(ESM_MODEL)
    model = EsmForMaskedLM.from_pretrained(ESM_MODEL).eval()
    rev = getattr(model.config, '_commit_hash', None)
    log('')
    log(f'PHASE esm -- {ESM_MODEL} rev={rev} dim={model.config.hidden_size}, '
        f'locked PCA {PCA_ID} (64 comps, EVR {pca["explained_variance_ratio_total"]:.4f}, '
        f'fitted on {pca["n_train_contexts"]} cache_all TRAIN contexts) -- NOT refitted')
    if rev != ESM_REVISION:
        log(f'  WARNING: revision {rev} != recorded {ESM_REVISION}')
    if model.config.hidden_size != comps.shape[1]:
        raise ValueError('model width does not match the locked PCA basis')

    rows, errors = [], []
    for p in sorted((OUT / 'cache').glob('*.json.gz')):
        ctx = BE.load_context(p)
        cid = ctx['context_id']
        dest = out / f'{cid}.npz'
        keys = [str(k) for k in ctx['keys']]
        if (not args.force and BE.embedding_done(dest, keys, ESM_MODEL)
                and BE.projection_current(dest, PCA_ID)):
            log(f'  {cid:20s} cached')
            rows.append({'context': cid, 'reused': True})
            continue
        t0 = time.monotonic()
        try:
            emb, entropy, windowed, gaps = BE.build_one(ctx, model, tok, 'cpu')
        except Exception as exc:  # recorded, never swallowed
            errors.append({'context': cid, 'error': repr(exc)[:400]})
            log(f'  {cid:20s} FAILED {exc!r}')
            continue
        emb16 = emb.astype(np.float16)
        # The exact projection build_esm.main applies, on the exact stored dtype.
        emb64 = ((emb16.astype(np.float32) - mean) @ comps.T).astype(np.float32)
        np.savez_compressed(dest, keys=np.array(keys, dtype=object).astype('U'),
                            emb=emb16, entropy=entropy,
                            model_id=np.array(ESM_MODEL), emb64=emb64,
                            pca_id=np.array(PCA_ID))
        rows.append({'context': cid, 'reused': False, 'residues': int(emb.shape[0]),
                     'windowed_chains': int(windowed), 'gap_adjacencies': int(gaps),
                     'seconds': round(time.monotonic() - t0, 1)})
        log(f'  {cid:20s} res={emb.shape[0]:5d} windowed={windowed} gaps={gaps} '
            f'{time.monotonic()-t0:.1f}s')
    write_json(OUT / 'esm_receipt.json',
               {'model_id': ESM_MODEL, 'model_revision': rev,
                'model_revision_expected': ESM_REVISION,
                'model_dim': model.config.hidden_size, 'licence': 'mit',
                'pca_artifact': str(PCA_PATH), 'pca_sha256': sha256(PCA_PATH),
                'pca_id': PCA_ID, 'pca_refitted': False,
                'pca_n_train_contexts': pca['n_train_contexts'],
                'pca_n_train_residues': pca['n_train_residues'],
                'pca_explained_variance_ratio_total': pca['explained_variance_ratio_total'],
                'script_sha256': sha256(HERE / 'build_esm.py'),
                'cif_dir': str(BE.CIF_DIR), 'out_dir': str(out),
                'contexts': rows, 'errors': errors})
    log(f'  {len(rows)}/{len(rows)+len(errors)} contexts projected into the locked basis')
    if errors:
        raise SystemExit('esm features incomplete')


# ---------------------------------------------------------------- phase: pack

def with_sweep_rooted_here(fn):
    """Run `fn` with sweep.HERE pointed at OUT.

    sweep builds every path off its module-level DATA: `DATA/atom_cache`,
    `DATA/esm_cache`, `DATA/patches/<block>`. Redirecting the single attribute
    makes both the pack writes and the patch reads land in this script's own tree
    and is what keeps the shared `prince-data/patches/` untouched.
    """
    old = SW.DATA
    SW.DATA = OUT
    try:
        return fn()
    finally:
        SW.DATA = old


def phase_pack(args) -> None:
    load_sweep()
    log('')
    log('PHASE pack -- sweep.phase_pack with sweep.HERE -> ' + str(OUT))
    for b in COMBO:
        d = OUT / 'patches' / b
        if args.force and d.exists():
            for f in d.glob('*.npz'):
                f.unlink()
    with_sweep_rooted_here(lambda: SW.phase_pack(
        Namespace(cache_dir='cache', blocks=list(COMBO))))
    widths = {}
    for b in COMBO:
        files = sorted((OUT / 'patches' / b).glob('*.npz'))
        with np.load(files[0], allow_pickle=False) as z:
            widths[b] = int(z['xp'].shape[1])
        log(f'  {b:5s} {len(files)} contexts, {widths[b]} packed columns')
    # The column layout the model expects: blocks in COMBO order, then the
    # 3-column patch meta. Checked against one shared cache_all context so a
    # width drift cannot pass silently.
    ref_ctx = sorted((SHARED_PATCHES / 'geom').glob('*.npz'))[0].stem
    ref = SW.patch_matrix(ref_ctx, COMBO)
    ours = with_sweep_rooted_here(lambda: SW.patch_matrix(context_id('PD-L1'), COMBO))
    if ref.shape[1] != ours.shape[1]:
        raise ValueError(f'column count {ours.shape[1]} != cache_all {ref.shape[1]}')
    log(f'  assembled matrix width {ours.shape[1]} == cache_all width '
        f'(blocks {"+".join(COMBO)} then [n_res, area, radius_gyration])')
    write_json(OUT / 'pack_widths.json',
               {'blocks': list(COMBO), 'packed_widths': widths,
                'assembled_width': int(ours.shape[1]),
                'cache_all_reference_context': ref_ctx})


# ---------------------------------------------------------------- phase: train

def phase_train(args) -> None:
    load_sweep()
    lock = json.loads(LOCK_PATH.read_text())
    cfg = lock['config']
    if (cfg['kind'] != 'patch_classifier' or cfg['depth'] != 6
            or tuple(cfg['combo']) != COMBO):
        raise ValueError(f'sweep_lock.json is not the expected locked model: {cfg}')
    leak = json.loads((REF / 'leakage.json').read_text())
    bad = set(leak['excluded_clusters'])
    if leak['tier_used_for_exclusion'] != 0.30:
        raise ValueError(f'leakage.json tier {leak["tier_used_for_exclusion"]} != 0.30')

    log('')
    log(f'PHASE train -- locked model {lock["winner"]} ({cfg})')
    log(f'  locked on: {lock["primary_endpoint"]}')
    log(f'  CV majority_hit@3 {lock["cv_summary"]["majority_hit"]["3"]["mean"]:.3f} '
        f'+/- {lock["cv_summary"]["majority_hit"]["3"]["sd"]:.3f} vs random '
        f'{lock["random_control_cv"]["majority_hit"]["3"]:.3f}')

    t0 = time.monotonic()
    index = SW.load_index(CACHE_ALL)
    for r in index:
        r.pop('conflict', None)   # NMS-only; dropping it frees ~150 MB
    log(f'  sweep.load_index(cache_all): {len(index)} interfaces, '
        f'{time.monotonic()-t0:.0f}s')
    for a, b in (('train', 'val'), ('train', 'test'), ('val', 'test')):
        ca = {r['cluster'] for r in index if r['split'] == a}
        cb = {r['cluster'] for r in index if r['split'] == b}
        if ca & cb:
            raise ValueError(f'cluster leakage between {a} and {b}')
    have = set.intersection(*[{p.stem for p in (SHARED_PATCHES / b).glob('*.npz')}
                              for b in COMBO])
    train = [r for r in index if r['split'] == 'train' and r['context'] in have]
    clean = [r for r in train if r['cluster'] not in bad]
    log(f'  naive: {len(train)} train interfaces / '
        f'{len({r["cluster"] for r in train})} clusters')
    log(f'  clean: {len(clean)} train interfaces / '
        f'{len({r["cluster"] for r in clean})} clusters  '
        f'({len(train)-len(clean)} interfaces, '
        f'{len({r["cluster"] for r in train})-len({r["cluster"] for r in clean})} '
        f'clusters excluded at the >=30% identity tier)')
    log(f'  excluded clusters ({len(bad)}): {", ".join(sorted(bad))}')

    (OUT / 'models').mkdir(parents=True, exist_ok=True)
    stats_out = {}
    for name, rows in (('clean', clean), ('naive', train)):
        dest = OUT / 'models' / f'{lock["winner"]}__{name}.json'
        if dest.exists() and not args.force:
            log(f'  {name}: cached {dest.name}')
            stats_out[name] = {'cached': True, 'interfaces': len(rows),
                               'clusters': len({r['cluster'] for r in rows})}
            continue
        t0 = time.monotonic()
        rng = np.random.default_rng(SW.SEED)
        Xy = SW.build_training(rows, COMBO, rng, cfg['kind'])
        model = SW.fit(Xy, cfg)
        model.save_model(str(dest))
        stats_out[name] = {'interfaces': len(rows),
                           'clusters': len({r['cluster'] for r in rows}),
                           'rows': int(Xy[0].shape[0]), 'cols': int(Xy[0].shape[1]),
                           'positives': int(Xy[1].sum()),
                           'seconds': round(time.monotonic() - t0, 1)}
        log(f'  {name}: {Xy[0].shape[0]} patch rows x {Xy[0].shape[1]} cols, '
            f'{int(Xy[1].sum())} positive, {time.monotonic()-t0:.0f}s -> {dest.name}')
        del Xy, model
    write_json(OUT / 'training.json',
               {'lock': lock, 'combo': list(COMBO),
                'excluded_clusters': sorted(bad),
                'exclusion_source': str(REF / 'leakage.json'),
                'exclusion_tier': leak['tier_used_for_exclusion'],
                'contexts_with_all_blocks': len(have), 'models': stats_out})


# ---------------------------------------------------------------- phase: eval

def site_mapping(d: dict, residues: list[int]) -> dict:
    """score_site_benchmark.site_mapping, verbatim."""
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
    out.update({'copy': best, 'indices': sorted({i for _, i in percopy[best]}),
                'resolved_fraction': len({p for p, _ in percopy[best]}) / len(residues)})
    return out


def phase_eval(args) -> None:
    load_sweep()
    import xgboost as xgb

    lock = json.loads(LOCK_PATH.read_text())
    bm = pd.read_csv(BENCH / 'site_benchmark.csv')
    avail = pd.read_csv(BENCH / 'structure_availability_sites.csv')
    frac_ref = dict(zip(avail.site_id, avail.frac_scoreable))
    models = {}
    for name in ('clean', 'naive'):
        m = xgb.XGBClassifier()
        m.load_model(str(OUT / 'models' / f'{lock["winner"]}__{name}.json'))
        models[name] = m

    log('')
    log('PHASE eval -- site mapping and scoring')
    rows, dropped = [], []
    for target in targets():
        with gzip.open(OUT / 'cache' / f'{context_id(target)}.json.gz', 'rt') as s:
            d = json.load(s)
        X = with_sweep_rooted_here(
            lambda: SW.patch_matrix(context_id(target), COMBO))
        if X is None or X.shape[0] != d['n_patches']:
            raise ValueError(f'{target}: patch matrix missing or mis-shaped')
        preds = {name: m.predict_proba(X)[:, 1] for name, m in models.items()}
        pat = [set(p) for p in d['patch_indices']]
        relsasa = np.asarray(d['relative_sasa'])
        patch_exposure = np.asarray([float(np.mean(relsasa[list(p)])) for p in pat])

        n_ok = 0
        for s in bm[bm.target == target].itertuples():
            res = [int(x) for x in str(s.site_residues_consensus).split(';') if x]
            mp = site_mapping(d, res)
            ref = frac_ref.get(s.site_id)
            agree = None if ref is None or ref != ref else abs(mp['resolved_fraction'] - ref)
            if mp['resolved_fraction'] < MIN_RESOLVED_FRACTION:
                dropped.append({'site_id': s.site_id, 'target': target,
                                'reason': f'resolved_fraction below {MIN_RESOLVED_FRACTION}',
                                'resolved_fraction': mp['resolved_fraction'],
                                'benchmark_frac_scoreable': ref,
                                'n_site_residues': len(res),
                                'estimable': bool(s.estimable)})
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
                # EXACTLY the earlier run's definition, so the two runs compare.
                row[f'score_meanoverlap_{name}'] = (
                    float(np.mean(pr[touching])) if len(touching) else float(pr[best]))
                # The brief also describes an overlap-WEIGHTED mean; reported
                # beside it rather than substituted for it.
                row[f'score_ovlpweighted_{name}'] = (
                    float(np.average(pr[touching], weights=inter[touching]))
                    if len(touching) else float(pr[best]))
            rows.append(row)
            n_ok += 1
        log(f'  {target:14s} {n_ok:3d} sites scored, '
            f'{sum(1 for x in dropped if x["target"]==target):2d} dropped  '
            f'(patches={d["n_patches"]}, residues={d["n_residues"]})')

    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'site_scores.csv', index=False)
    write_json(OUT / 'dropped_sites.json', dropped)

    cmp = df.dropna(subset=['frac_abs_diff_vs_benchmark'])
    log('')
    log("MAPPING ASSERTION vs the benchmark's structure_availability_sites.csv")
    log(f'  {len(cmp)} sites comparable; mean |diff| in resolved fraction '
        f'{cmp.frac_abs_diff_vs_benchmark.mean():.4f}, '
        f'max {cmp.frac_abs_diff_vs_benchmark.max():.4f}, '
        f'{int((cmp.frac_abs_diff_vs_benchmark > 0.05).sum())} differ by > 0.05')
    log(f'  {len(dropped)} sites dropped for resolved fraction < {MIN_RESOLVED_FRACTION}: '
        f'{", ".join(sorted(x["site_id"] for x in dropped)) or "none"}')
    analyse(df, dropped, lock)


# ---------------------------------------------------------------- analysis

def per_target_rho(df: pd.DataFrame, col: str) -> dict:
    out = {}
    for t, g in df.groupby('target'):
        if len(g) < 3 or g.success_rate.nunique() < 2 or g[col].nunique() < 2:
            out[t] = {'n': int(len(g)), 'rho': None, 'p': None,
                      'reason': 'no variance / n<3',
                      'distinct_scores': int(g[col].nunique())}
            continue
        r = stats.spearmanr(g[col], g.success_rate)
        out[t] = {'n': int(len(g)), 'rho': float(r.statistic), 'p': float(r.pvalue),
                  'distinct_scores': int(g[col].nunique())}
    return out


def aggregate(rhos: dict, group: list[str]) -> dict:
    vals = [(t, rhos[t]) for t in group if t in rhos and rhos[t]['rho'] is not None]
    if not vals:
        return {'n_targets': 0, 'n_targets_unrankable': len(group)}
    r = np.array([v['rho'] for _, v in vals])
    n = np.array([v['n'] for _, v in vals])
    pos = int((r > 0).sum())
    sign = stats.binomtest(pos, len(r), 0.5)
    z = np.array([stats.norm.isf(v['p'] / 2) * np.sign(v['rho']) for _, v in vals])
    w = np.sqrt(np.maximum(n - 1, 1))
    zc = float((w * z).sum() / np.sqrt((w ** 2).sum()))
    return {'n_targets': len(r),
            'n_targets_unrankable': len([t for t in group
                                         if t in rhos and rhos[t]['rho'] is None]),
            'mean_rho': float(r.mean()), 'median_rho': float(np.median(r)),
            'sd_rho': float(r.std(ddof=1)) if len(r) > 1 else None,
            'n_positive': pos, 'sign_test_p': float(sign.pvalue),
            'stouffer_z': zc, 'stouffer_p_two_sided': float(2 * stats.norm.sf(abs(zc))),
            'per_target': {t: v['rho'] for t, v in vals}}


def null_for(est: pd.DataFrame, col: str, group: list[str], reps: int, seed: int):
    """Two nulls, both within-target and both macro-averaged the same way.

    `permute` reshuffles the ACTUAL score vector, so it preserves the score's tie
    structure -- which matters here because ties are the dominant failure mode.
    `uniform` draws fresh continuous scores, which is what the geom-only run used,
    kept so the two runs are comparable.
    """
    rng = np.random.default_rng(seed)
    groups = {t: (g.success_rate.to_numpy(), g[col].to_numpy())
              for t, g in est.groupby('target')}
    per = {k: collections.defaultdict(list) for k in ('permute', 'uniform')}
    for _ in range(reps):
        for t, (y, v) in groups.items():
            if len(y) < 3 or len(set(y)) < 2:
                continue
            if len(set(v)) > 1:
                per['permute'][t].append(
                    stats.spearmanr(rng.permutation(v), y).statistic)
            per['uniform'][t].append(stats.spearmanr(rng.random(len(y)), y).statistic)
    out = {}
    for kind, acc in per.items():
        ptar = {t: {'mean': float(np.mean(v)), 'sd': float(np.std(v)),
                    'q025': float(np.quantile(v, .025)),
                    'q975': float(np.quantile(v, .975))}
                for t, v in acc.items() if v}
        agg = []
        for i in range(reps):
            vals = [acc[t][i] for t in group if t in acc and i < len(acc[t])]
            if vals:
                agg.append(float(np.mean(vals)))
        out[kind] = {'per_target': ptar,
                     'macro_over_group': {
                         'targets_contributing': [t for t in group if t in acc and acc[t]],
                         'mean': float(np.mean(agg)), 'sd': float(np.std(agg)),
                         'q025': float(np.quantile(agg, .025)),
                         'q975': float(np.quantile(agg, .975))} if agg else None}
    return out


def tie_fractions(est: pd.DataFrame, cols: list[str]) -> dict:
    out = {}
    for col in cols:
        tot = tied = 0
        per = {}
        for t, g in est.groupby('target'):
            v = g[col].to_numpy()
            tt = td = 0
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    tt += 1
                    td += int(v[i] == v[j])
            per[t] = {'pairs': tt, 'tied': td,
                      'tied_fraction': td / tt if tt else None,
                      'n_sites': int(len(g)), 'distinct_scores': int(g[col].nunique())}
            tot += tt
            tied += td
        out[col] = {'pairs': tot, 'tied': tied,
                    'tied_fraction': tied / tot if tot else None, 'per_target': per}
    return out


def analyse(df: pd.DataFrame, dropped: list, lock: dict) -> None:
    est = df[df.estimable].copy()
    power = pd.read_csv(BENCH / 'power_analysis.csv')
    mdd = dict(zip(power.target, power.mdd_80pct_power))

    score_cols = [c for c in df.columns if c.startswith('score_')]
    arms = {c: per_target_rho(est, c) for c in score_cols}
    arms['exposure_site_mean_relsasa'] = per_target_rho(est, 'site_mean_relsasa')
    arms['exposure_best_patch_relsasa'] = per_target_rho(est, 'best_patch_mean_relsasa')

    PRIMARY = 'score_bestjac_clean'
    nulls = null_for(est, PRIMARY, PRIMARY_TARGETS, RANDOM_REPS, SEED)

    log('')
    log('=' * 78)
    log('PER-TARGET WITHIN-TARGET SPEARMAN rho  (estimable sites only)')
    log('=' * 78)
    log('POWER CEILING, quoted up front: detectable |rho| at 80% power is ~0.33-0.38')
    log('over the primary 7; minimum detectable DIFFERENCE between two sites of one')
    log('target is 0.63-0.79 in absolute success rate. "No effect detected" here is')
    log('NOT "no effect exists". Pooled scoring is forbidden: between-target variance')
    log('is 26.0% of total and a target-mean-only predictor scores pooled rho = 0.750.')
    log('')

    ties = tie_fractions(est, score_cols + ['site_mean_relsasa',
                                            'best_patch_mean_relsasa'])
    log('SCORE DEGENERACY (within-target site pairs given an identical score)')
    for c, v in ties.items():
        log(f"  {c:32s} {v['tied']:4d}/{v['pairs']:4d} "
            f"({100*v['tied_fraction']:.1f}%)")
    log('')
    log(f"  {'target':14s} {'n':>3s} {'distinct patch':>14s} {'distinct J-score':>16s} "
        f"{'distinct M-score':>16s} {'mean best Jaccard':>18s}")
    for t in PRIMARY_TARGETS + SECONDARY_TARGETS + EXCLUDED_TARGETS:
        g = est[est.target == t]
        if not len(g):
            continue
        log(f"  {t:14s} {len(g):3d} {g.best_patch.nunique():14d} "
            f"{g[PRIMARY].nunique():16d} "
            f"{g['score_meanoverlap_clean'].nunique():16d} "
            f"{g.best_jaccard.mean():18.3f}")

    vs_exp = {}
    for t, g in est.groupby('target'):
        if len(g) >= 3 and g[PRIMARY].nunique() > 1 and g.site_mean_relsasa.nunique() > 1:
            vs_exp[t] = float(stats.spearmanr(g[PRIMARY], g.site_mean_relsasa).statistic)
    log('')
    log('EXPOSURE DIAGNOSTIC -- within-target rho(locked clean-J score, site mean rel. SASA)')
    log('  ' + '  '.join(f'{t}={v:+.2f}' for t, v in sorted(vs_exp.items())))
    vv = list(vs_exp.values())
    log(f'  mean over {len(vv)} targets: {np.mean(vv):+.3f}; '
        f'negative on {sum(1 for v in vv if v < 0)}/{len(vv)}')

    head = (f"  {'target':14s} {'n':>3s} {'MDD':>5s} {'clean-J':>8s} {'clean-M':>8s} "
            f"{'naive-J':>8s} {'expos':>8s} {'perm null95':>16s}")
    for label, group in (('PRIMARY 7 (heterogeneity established)', PRIMARY_TARGETS),
                         ('SECONDARY', SECONDARY_TARGETS),
                         ('EXCLUDED from ranking', EXCLUDED_TARGETS)):
        log('')
        log(f'-- {label}')
        log(head)
        for t in group:
            def cell(arm):
                v = arms[arm].get(t, {})
                r = v.get('rho')
                return f'{r:+8.3f}' if r is not None else f'{"tied/na":>8s}'
            a = arms[PRIMARY].get(t, {})
            ns = nulls['permute']['per_target'].get(t, {})
            m = mdd.get(t)
            lo = ns.get('q025', float('nan'))
            hi = ns.get('q975', float('nan'))
            log(f"  {t:14s} {a.get('n', 0):3d} "
                f"{(f'{m:.2f}' if m == m else '  -'):>5s} "
                f"{cell(PRIMARY)} {cell('score_meanoverlap_clean')} "
                f"{cell('score_bestjac_naive')} {cell('exposure_site_mean_relsasa')} "
                f"[{lo:+.2f},{hi:+.2f}]")

    log('')
    log('AGGREGATE (macro-average of within-target rho)')
    summary = {'arms': {}}
    for name, rhos in arms.items():
        summary['arms'][name] = {
            'primary': aggregate(rhos, PRIMARY_TARGETS),
            'secondary': aggregate(rhos, SECONDARY_TARGETS),
            'all_informative': aggregate(rhos, PRIMARY_TARGETS + SECONDARY_TARGETS),
            'no_training_overlap': aggregate(rhos, NO_OVERLAP_SUBSET),
            'per_target': rhos}
        p = summary['arms'][name]['primary']
        if p['n_targets']:
            log(f"  {name:32s} primary mean rho {p['mean_rho']:+.3f} "
                f"(n={p['n_targets']} rankable, {p['n_targets_unrankable']} tied out, "
                f"median {p['median_rho']:+.3f}, {p['n_positive']}/{p['n_targets']} "
                f"positive, Stouffer z {p['stouffer_z']:+.2f} "
                f"p={p['stouffer_p_two_sided']:.3f})")
        else:
            log(f"  {name:32s} primary: 0 rankable targets")

    mnull = nulls['permute']['macro_over_group']
    unull = nulls['uniform']['macro_over_group']
    log('')
    log(f'RANDOM CONTROL on the primary 7 ({RANDOM_REPS} reps, within-target, '
        f'then macro-averaged)')
    log(f"  within-target PERMUTATION of the actual score (preserves its ties): "
        f"mean {mnull['mean']:+.4f} sd {mnull['sd']:.4f} "
        f"95% [{mnull['q025']:+.3f}, {mnull['q975']:+.3f}]  "
        f"over {len(mnull['targets_contributing'])} targets")
    log(f"  uniform random scores (the geom-only run's control): "
        f"mean {unull['mean']:+.4f} sd {unull['sd']:.4f} "
        f"95% [{unull['q025']:+.3f}, {unull['q975']:+.3f}]  "
        f"over {len(unull['targets_contributing'])} targets")
    obs = summary['arms'][PRIMARY]['primary'].get('mean_rho')
    if obs is not None:
        inside = mnull['q025'] <= obs <= mnull['q975']
        log('')
        log(f'  OBSERVED primary mean rho ({PRIMARY}) = {obs:+.3f}')
        log(f'  {"INSIDE" if inside else "OUTSIDE"} the permutation null 95% interval '
            f'-> {"NULL: no effect detected" if inside else "effect detected"}')

    log('')
    log('NO-TRAINING-OVERLAP SUBSET (TREM2, BHRF1, IL-7Ra)')
    for name in (PRIMARY, 'score_meanoverlap_clean', 'score_bestjac_naive',
                 'exposure_site_mean_relsasa'):
        v = summary['arms'][name]['no_training_overlap']
        if v['n_targets']:
            log(f"  {name:32s} mean rho {v['mean_rho']:+.3f} over {v['n_targets']} "
                f"targets ({v['n_targets_unrankable']} tied out): "
                + ', '.join(f'{t}={r:+.2f}' for t, r in v['per_target'].items()))
        else:
            log(f"  {name:32s} 0 rankable targets ({v['n_targets_unrankable']} tied out)")

    # Pooled, computed ONLY to show why it is forbidden.
    pooled = stats.spearmanr(est[PRIMARY], est.success_rate)
    tmean = est.groupby('target').success_rate.transform('mean')
    pooled_tm = stats.spearmanr(tmean, est.success_rate)
    log('')
    log('POOLED (reported as a trap, never as a result)')
    log(f'  pooled rho(locked clean-J, success) = {pooled.statistic:+.3f}; '
        f'pooled rho(target mean only, success) = {pooled_tm.statistic:+.3f}')

    summary.update({
        'lock': lock, 'combo': list(COMBO),
        'primary_score_column': PRIMARY,
        'random_control': nulls, 'n_random_reps': RANDOM_REPS,
        'score_degeneracy': ties,
        'exposure_diagnostic': {'per_target': vs_exp,
                                'mean': float(np.mean(vv)) if vv else None,
                                'n_negative': sum(1 for v in vv if v < 0),
                                'n_targets': len(vv)},
        'power_ceiling': {
            'detectable_abs_rho_80pct_power_primary7': [0.33, 0.38],
            'per_site_mdd_absolute_success_rate': [0.63, 0.79],
            'note': 'no effect detected is not no effect exists'},
        'pooled_invalid': {'pooled_rho': float(pooled.statistic),
                           'pooled_rho_target_mean_only': float(pooled_tm.statistic),
                           'why': 'between-target variance is 26.0% of total'},
        'n_sites_scored': int(len(df)), 'n_estimable_scored': int(len(est)),
        'n_dropped': len(dropped),
        'target_groups': {'primary': PRIMARY_TARGETS, 'secondary': SECONDARY_TARGETS,
                          'excluded': EXCLUDED_TARGETS,
                          'no_training_overlap': NO_OVERLAP_SUBSET},
    })
    write_json(OUT / 'results.json', summary)

    # comparison against the geom-only stand-in run, same columns
    prev = json.loads((REF / 'results.json').read_text())
    comp = {}
    for name in ('score_bestjac_clean', 'score_meanoverlap_clean',
                 'score_bestjac_naive', 'exposure_site_mean_relsasa'):
        a = prev['arms'].get(name, {}).get('primary', {})
        b = summary['arms'].get(name, {}).get('primary', {})
        comp[name] = {'geom_only': {k: a.get(k) for k in
                                   ('n_targets', 'mean_rho', 'median_rho', 'n_positive')},
                      'locked_geom_atom_esm': {k: b.get(k) for k in
                                               ('n_targets', 'mean_rho', 'median_rho',
                                                'n_positive')}}
    write_json(OUT / 'comparison_vs_geom_only.json', comp)
    log('')
    log('VS THE GEOM-ONLY STAND-IN RUN (site_scoring/results.json), primary 7')
    log(f"  {'arm':32s} {'geom-only':>22s} {'locked geom+atom+esm':>24s}")
    for name, v in comp.items():
        a, b = v['geom_only'], v['locked_geom_atom_esm']
        def fmt(x):
            return (f"{x['mean_rho']:+.3f} (n={x['n_targets']})"
                    if x.get('mean_rho') is not None else 'n/a')
        log(f'  {name:32s} {fmt(a):>22s} {fmt(b):>24s}')


# ---------------------------------------------------------------- phase: receipt

def phase_receipt(args) -> None:
    inputs = {}
    for p in [LOCK_PATH, PCA_PATH, HERE / 'sweep.py', HERE / 'build_cache_all.py',
              HERE / 'build_atom_features.py', HERE / 'build_esm.py',
              DATA / 'atom_feature_names.json', HERE / 'score_site_benchmark.py',
              Path(__file__), BENCH / 'site_benchmark.csv',
              BENCH / 'structure_availability_sites.csv', BENCH / 'power_analysis.csv',
              BENCH / 'downloads' / 'target_constructs.parquet',
              REF / 'leakage.json', REF / 'leakage_table.csv', REF / 'results.json',
              ROOT / 'src/hotspot_preflight/surface.py',
              ROOT / 'src/hotspot_preflight/predict/features.py',
              ROOT / 'src/hotspot_preflight/checks/sasa.py']:
        inputs[str(p)] = sha256(p) if p.exists() else None
    for t in targets():
        p = stripped_cif(t)
        inputs[str(p)] = sha256(p)

    counts = {
        'contexts_built': len(list((OUT / 'cache').glob('*.json.gz'))),
        'atom_npz': len(list((OUT / 'atom_cache').glob('*.npz'))),
        'esm_npz': len(list((OUT / 'esm_cache').glob('*.npz'))),
        'patches': {b: len(list((OUT / 'patches' / b).glob('*.npz'))) for b in COMBO},
    }
    res = json.loads((OUT / 'results.json').read_text()) \
        if (OUT / 'results.json').exists() else {}
    train = json.loads((OUT / 'training.json').read_text()) \
        if (OUT / 'training.json').exists() else {}
    receipt = {
        'script': str(Path(__file__).resolve()),
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'python': sys.executable,
        'question': 'does the CV-locked PRINCE site model (patch_classifier_d6_'
                    'geom+atom+esm) predict minibinder designability per site?',
        'locked_model': json.loads(LOCK_PATH.read_text()),
        'pca_id': PCA_ID, 'pca_refitted': False,
        'esm_model': ESM_MODEL, 'esm_revision_expected': ESM_REVISION,
        'exclusion_list_source': str(REF / 'leakage.json'),
        'excluded_clusters': train.get('excluded_clusters'),
        'exclusion_tier': train.get('exclusion_tier'),
        'training': train.get('models'),
        'counts': counts,
        'targets_failed': [],
        'controls': {
            'random_control_reps': RANDOM_REPS,
            'random_control_kinds': ['within-target permutation of the actual score',
                                     'within-target uniform random scores'],
            'macro_null_primary7': (res.get('random_control', {})
                                    .get('permute', {}).get('macro_over_group')),
            'exposure_arm': 'exposure_site_mean_relsasa / exposure_best_patch_relsasa',
            'pooled_trap': res.get('pooled_invalid'),
        },
        'power_ceiling': res.get('power_ceiling'),
        'headline': (res.get('arms', {}).get('score_bestjac_clean', {}).get('primary')),
        'substitutions': [
            'build_esm.py has no flag to apply an existing PCA without refitting '
            '(main() always calls fit_pca), so its build_one/chain_sequences/embed '
            'are driven from this script and the LOCKED components/mean are applied '
            'with build_esm.main\'s own expression, from the same float16 stored '
            'dtype. Validated: projection_id(loaded components, mean) == '
            f'{PCA_ID}, the recorded pca_id.',
            'build_atom_features.py and build_esm.py locate coordinates through a '
            'module-level CIF_DIR with no CLI override, so CIF_DIR is reassigned to '
            'a symlink tree of the stripped benchmark structures. Neither file is '
            'modified; build_one is the --workers 1 code path.',
            'sweep.phase_pack and sweep.patch_matrix build paths off sweep.HERE; it '
            'is temporarily repointed at this output tree so nothing is written into '
            'the shared prince-data/patches/.',
            'The 51-feature geometry is recomputed here rather than read from '
            'site_scoring/targets/*.npz, then asserted bit-for-bit equal to it '
            '(plus keys, patch pool, keymap and pos2res).',
        ],
        'input_sha256': inputs,
    }
    write_json(OUT / 'RECEIPT.json', receipt)
    # Phases run as separate processes (libomp), so the human-readable receipt is
    # the concatenation of their logs rather than this process's own RECEIPT list.
    parts = []
    for name in ('cache', 'atom', 'esm', 'pack', 'train', 'eval'):
        p = OUT / f'{name}.log'
        if p.exists():
            parts.append(p.read_text())
    (OUT / 'RECEIPT.txt').write_text('\n'.join(parts) + '\n')
    log('')
    log(f'receipt -> {OUT/"RECEIPT.json"}')


# ---------------------------------------------------------------- main

PHASES = {'cache': phase_cache, 'atom': phase_atom, 'esm': phase_esm,
          'pack': phase_pack, 'train': phase_train, 'eval': phase_eval,
          'receipt': phase_receipt}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--phase', required=True,
                    choices=list(PHASES) + ['all'])
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase == 'all':
        # One subprocess per phase: see the libomp note at the top of the module.
        import subprocess
        for name in PHASES:
            cmd = [sys.executable, str(Path(__file__).resolve()), '--phase', name]
            if args.force:
                cmd.append('--force')
            print(f'### running {name}', flush=True)
            if subprocess.call(cmd) != 0:
                raise SystemExit(f'phase {name} failed')
        return
    log(f'### designability_transfer {args.phase} '
        f'{time.strftime("%Y-%m-%dT%H:%M:%S")}')
    PHASES[args.phase](args)
    (OUT / f'{args.phase}.log').write_text('\n'.join(RECEIPT) + '\n')


if __name__ == '__main__':
    main()
