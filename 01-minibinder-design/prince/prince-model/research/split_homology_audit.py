"""Remote-homology audit of the PRINCE antigen train/test split, and a rescore of the
locked model on the homology-clean test subset.

Why this exists
---------------
`hotspot-preflight/benchmark/cluster.py` builds antigen clusters by transitively joining
antigen chains on **UniProt accession OR exact sequence identity only**. Its own docstring
concedes the gap:

    "This guarantees accession/exact-sequence disjointness, not remote-homology
     disjointness: related proteins with different accessions and sequences may still
     cross splits."

So a reviewer's objection -- that the held-out test clusters may still contain close
homologues of training antigens (viral strain variants, orthologues, re-deposited
constructs under a new accession) -- is not answered by the existing split. This script
measures the size of that gap with BLAST and then re-reads the test split on the subset of
clusters that survive a homology filter, so the headline can be quoted with or without the
homologous clusters.

Sequence provenance
-------------------
Antigen sequences are reconstructed from the LOCAL structure cache
(`$PRINCE_DATA_DIR/cache_all/*.json.gz`), not from the network. Each cache file
carries a per-residue feature matrix whose `aa_XXX` columns are a one-hot of the residue
type (verified: every row sums to exactly 1.0), so the modelled sequence of every cached
chain is recoverable exactly, with no network calls. Two consequences are stated rather
than hidden:

  * these are MODELLED sequences -- unresolved loops are absent and the flanking segments
    are collapsed, so a chain's sequence here can be shorter than its SEQRES;
  * `aa_UNK` residues decode to `X`.

Neither biases the audit toward a clean answer: missing residues can only *lower* measured
identity, so the reported leakage is a floor, not a ceiling.

Identity definition (stated, because the number depends on it)
--------------------------------------------------------------
For an HSP between query q and subject s, with `nident` identical positions and
`length` aligned columns:

    raw_pident        = BLAST pident            (identity over the aligned region only)
    coverage_corrected = 100 * nident / min(qlen, slen)

The coverage-corrected number is the headline, because raw pident alone lets a 30-residue
patch of 95% identity masquerade as a 95%-identical protein. Both are reported.

An HSP must *qualify* before it counts as homology:

    e-value <= 1e-3  AND  length >= 50  AND  length >= 0.5 * min(qlen, slen)

with the absolute 50-column floor relaxed to `0.5 * min(qlen, slen)` when the shorter
sequence is itself under 50 residues (peptide/short antigens, which would otherwise be
unjudgeable). A permissive variant (e <= 1e-3, length >= 25, no coverage requirement) is
also computed as a sensitivity check, so a reviewer can see whether the tier table hinges
on the filter. Multi-HSP pairs take the single best HSP by coverage-corrected identity --
HSP identities are never summed, which would double-count repeats.

A cluster's `max_identity_to_train` is the maximum over all of that cluster's chain
sequences of the maximum over all train-split chain sequences.

Known limitation, stated up front: BLAST is not a remote-homology detector. It reliably
finds pairs down to ~25-30% identity; structural homologues below that (the regime that
needs HHsearch/Foldseek) can be missed. mmseqs is not installed on this machine and was
not installed for this audit. So the >=30% tier is a lower bound on true remote homology.

Phases
------
  seq    -- cache -> per-(context, chain) sequences + split/cluster attribution
  blast  -- makeblastdb(train) + blastp(test vs train, val vs train); temp DB removed
  tier   -- per-cluster max identity, tier table, named example pairs
  score  -- reload the LOCKED, ALREADY-REFIT model and read test on each subset,
            each against its own random-selection control
  all    -- the above, in order

Nothing here refits a model: `patch_classifier_d6_geom+atom+esm__refit_train.json` is
loaded as saved. `sweep.py` / `recovery_counts.py` are imported, never modified.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, collections, gzip, json, os, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sweep as S  # noqa: E402  (imported, not modified)

CACHE = (DATA / "cache_all")
OUT = (DATA / "split_audit")
MODEL = MODEL
MANIFEST = (REPO / "data/eval/prince_connected.manifest.csv")
BLASTDIR = (DATA / "split_audit/_blast_tmp")

KS = S.KS
TIERS = (90, 70, 50, 30)
RANDOM_REPS = 400          # matches sweep.py's RANDOM_REPS so the full-test control reproduces
EVALUE_MAX = 1e-3
MIN_ALN = 50
MIN_COV_FRAC = 0.5
PERMISSIVE_MIN_ALN = 25

AA3 = {'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E',
       'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F',
       'PRO': 'P', 'SER': 'S', 'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V', 'UNK': 'X'}

FIELDS = ('qseqid sseqid pident length nident mismatch gapopen qlen slen '
          'qstart qend sstart send evalue bitscore')


def write(p, d):
    Path(p).write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


# ------------------------------------------------------------------ phase: seq

def phase_seq(_args):
    """Decode every cached antigen chain's modelled sequence from the aa one-hot block."""
    files = sorted(CACHE.glob('*.json.gz'))
    recs = []                                  # one per (context, chain)
    skipped_no_patches = 0
    multi_cluster_contexts, multi_split_contexts = [], []
    onehot_violations = []
    t0 = time.monotonic()
    for i, f in enumerate(files, 1):
        with gzip.open(f, 'rt') as s:
            ctx = json.load(s)
        if not ctx['patches']:
            skipped_no_patches += 1
            continue
        names = ctx['feature_names']
        cols = [(j, n[3:]) for j, n in enumerate(names) if n.startswith('aa_')]
        X = np.asarray(ctx['features'], dtype=np.float32)[:, [j for j, _ in cols]]
        rs = X.sum(1)
        if not (np.allclose(rs, 1.0, atol=1e-4)):
            onehot_violations.append({'context': ctx['context_id'],
                                      'rowsum_min': float(rs.min()), 'rowsum_max': float(rs.max())})
            continue
        letters = [AA3[cols[j][1]] for j in X.argmax(1)]
        # keys look like 'A:115: ' -> chain is everything before the first ':'
        chains = [k.split(':', 1)[0] for k in ctx['keys']]
        clusters = sorted({inst['cluster'] for inst in ctx['instances']})
        splits = sorted({inst['split'] for inst in ctx['instances']})
        if len(clusters) > 1:
            multi_cluster_contexts.append({'context': ctx['context_id'], 'pdb': ctx['pdb'],
                                           'clusters': clusters})
        if len(splits) > 1:
            multi_split_contexts.append({'context': ctx['context_id'], 'pdb': ctx['pdb'],
                                         'splits': splits})
        byc = collections.defaultdict(list)
        for ch, aa in zip(chains, letters):
            byc[ch].append(aa)
        for ch, aas in byc.items():
            recs.append({'context': ctx['context_id'], 'pdb': ctx['pdb'], 'chain': ch,
                         'seq': ''.join(aas), 'clusters': clusters, 'splits': splits,
                         'n_instances': len(ctx['instances'])})
        if i % 1000 == 0:
            print(f'  {i}/{len(files)} contexts  {i/(time.monotonic()-t0):.0f}/s', flush=True)

    # Attribute each unique sequence to the splits/clusters it occurs in. Under
    # exact-sequence clustering an identical sequence must land in exactly one cluster;
    # any exception is itself a 100%-identity leak and is reported, not swallowed.
    byseq = collections.defaultdict(lambda: {'clusters': set(), 'splits': set(), 'chains': []})
    for r in recs:
        e = byseq[r['seq']]
        e['clusters'].update(r['clusters'])
        e['splits'].update(r['splits'])
        e['chains'].append(f"{r['pdb']}_{r['chain']}")
    cross_split_exact, multi_cluster_exact = [], []
    for seq, e in byseq.items():
        if len(e['splits']) > 1:
            cross_split_exact.append({'splits': sorted(e['splits']),
                                      'clusters': sorted(e['clusters']),
                                      'chains': sorted(e['chains'])[:6], 'len': len(seq)})
        if len(e['clusters']) > 1:
            multi_cluster_exact.append({'clusters': sorted(e['clusters']),
                                        'chains': sorted(e['chains'])[:6], 'len': len(seq)})

    seqs = []
    for n, (seq, e) in enumerate(sorted(byseq.items(), key=lambda kv: kv[0])):
        seqs.append({'sid': f'seq{n:05d}', 'seq': seq, 'len': len(seq),
                     'clusters': sorted(e['clusters']), 'splits': sorted(e['splits']),
                     'chains': sorted(e['chains'])})

    # Manifest-side receipts, so cluster coverage can be reported honestly.
    man_clusters = collections.defaultdict(set)
    with MANIFEST.open() as f:
        hdr = f.readline().rstrip('\n').split(',')
        ci, si = hdr.index('cluster_id'), hdr.index('split')
        for line in f:
            p = line.rstrip('\n').split(',')
            man_clusters[p[si]].add(p[ci])

    cov = {}
    for sp in ('train', 'val', 'test'):
        have = {c for s in seqs if sp in s['splits'] for c in s['clusters']}
        have &= man_clusters[sp]
        cov[sp] = {'manifest_clusters': len(man_clusters[sp]),
                   'clusters_with_sequences': len(have),
                   'clusters_without_sequences': sorted(man_clusters[sp] - have),
                   'unique_sequences': sum(1 for s in seqs if sp in s['splits'])}

    receipt = {
        'source': 'local structure cache only; zero network calls',
        'cache_dir': str(CACHE),
        'cache_files': len(files),
        'cache_files_skipped_no_patches': skipped_no_patches,
        'method': ('per-residue aa_XXX one-hot columns of the cache feature matrix '
                   'argmax-decoded to a 1-letter sequence; residues grouped by the chain '
                   'prefix of each cache key; aa_UNK -> X'),
        'caveat': ('MODELLED sequences: unresolved residues are absent and segments are '
                   'collapsed, so a chain can be shorter than its SEQRES. This can only '
                   'lower measured identity, so reported leakage is a floor.'),
        'chain_records': len(recs),
        'unique_sequences': len(seqs),
        'onehot_violations': onehot_violations,
        'contexts_spanning_multiple_clusters': len(multi_cluster_contexts),
        'contexts_spanning_multiple_splits': len(multi_split_contexts),
        'contexts_spanning_multiple_splits_examples': multi_split_contexts[:10],
        'exact_sequences_in_more_than_one_split': cross_split_exact,
        'exact_sequences_in_more_than_one_cluster': multi_cluster_exact[:20],
        'n_exact_sequences_in_more_than_one_cluster': len(multi_cluster_exact),
        'cluster_coverage': cov,
        'length_quantiles': {q: int(np.percentile([s['len'] for s in seqs], q))
                             for q in (1, 5, 25, 50, 75, 95, 99)},
        'sequences_shorter_than_50aa': sum(1 for s in seqs if s['len'] < 50),
    }
    write(OUT / 'sequences.json', seqs)
    write(OUT / 'sequence_receipt.json', receipt)
    for sp in ('train', 'val', 'test'):
        with (OUT / f'{sp}.fasta').open('w') as f:
            for s in seqs:
                if sp in s['splits']:
                    f.write(f">{s['sid']}\n{s['seq']}\n")
    print(json.dumps({k: v for k, v in receipt.items()
                      if k not in ('exact_sequences_in_more_than_one_cluster',
                                   'contexts_spanning_multiple_splits_examples')}, indent=2)[:3000])


# ---------------------------------------------------------------- phase: blast

def _blast(query, dbfasta, outfile, threads=4):
    BLASTDIR.mkdir(parents=True, exist_ok=True)
    db = BLASTDIR / 'traindb'
    if not (db.with_suffix('.phr').exists() or Path(str(db) + '.phr').exists()):
        subprocess.run(['/usr/local/bin/makeblastdb', '-in', str(dbfasta), '-dbtype', 'prot',
                        '-out', str(db)], check=True, capture_output=True, text=True)
    cmd = ['/usr/local/bin/blastp', '-query', str(query), '-db', str(db),
           '-outfmt', f'6 {FIELDS}', '-evalue', '10', '-max_target_seqs', '5000',
           '-num_threads', str(threads), '-comp_based_stats', '2']
    t0 = time.monotonic()
    with Path(outfile).open('w') as f:
        subprocess.run(cmd, check=True, stdout=f)
    print(f'  blastp {Path(query).name} -> {Path(outfile).name}  '
          f'{time.monotonic()-t0:.0f}s  {Path(outfile).stat().st_size/1e6:.1f} MB', flush=True)


def phase_blast(args):
    for sp in ('test', 'val'):
        _blast(OUT / f'{sp}.fasta', OUT / 'train.fasta', OUT / f'{sp}_vs_train.tsv',
               threads=args.threads)
    # Keep the disk clean: the DB is regenerable in seconds and swap here is tight.
    shutil.rmtree(BLASTDIR, ignore_errors=True)
    print('removed temporary BLAST database', flush=True)


# ----------------------------------------------------------------- phase: tier

def _qualifies(length, qlen, slen, evalue, permissive=False):
    if evalue > EVALUE_MAX:
        return False
    shorter = min(qlen, slen)
    if permissive:
        return length >= PERMISSIVE_MIN_ALN
    floor = MIN_ALN if shorter >= MIN_ALN else MIN_COV_FRAC * shorter
    return length >= floor and length >= MIN_COV_FRAC * shorter


def _best_hits(tsv, seqs, permissive=False):
    """sid -> best qualifying hit, by coverage-corrected identity."""
    meta = {s['sid']: s for s in seqs}
    best = {}
    f = FIELDS.split()
    with Path(tsv).open() as fh:
        for line in fh:
            p = line.rstrip('\n').split('\t')
            d = dict(zip(f, p))
            qlen, slen, length = int(d['qlen']), int(d['slen']), int(d['length'])
            nident, ev = int(d['nident']), float(d['evalue'])
            if not _qualifies(length, qlen, slen, ev, permissive):
                continue
            cci = 100.0 * nident / min(qlen, slen)
            cur = best.get(d['qseqid'])
            if cur is None or cci > cur['cov_corrected_identity']:
                best[d['qseqid']] = {
                    'query': d['qseqid'], 'subject': d['sseqid'],
                    'cov_corrected_identity': cci, 'raw_pident': float(d['pident']),
                    'aln_length': length, 'nident': nident, 'qlen': qlen, 'slen': slen,
                    'evalue': ev, 'bitscore': float(d['bitscore']),
                    'query_chains': meta[d['qseqid']]['chains'][:4],
                    'subject_chains': meta[d['sseqid']]['chains'][:4],
                    'query_clusters': meta[d['qseqid']]['clusters'],
                    'subject_clusters': meta[d['sseqid']]['clusters']}
    return best


def _manifest_cluster_split():
    """cluster_id -> split, from the manifest, which is authoritative.

    Needed because 18 unique modelled sequences occur in more than one split (see
    sequence_receipt.json). A sequence carries every cluster it appears in, so walking
    sequences alone would credit a test-split sequence's train-cluster ids to the test
    split and inflate the denominator (273 instead of 251)."""
    out = {}
    with MANIFEST.open() as f:
        hdr = f.readline().rstrip('\n').split(',')
        ci, si = hdr.index('cluster_id'), hdr.index('split')
        for line in f:
            p = line.rstrip('\n').split(',')
            out[p[ci]] = p[si]
    return out


def _unjudgeable(split, seqs, frac_x=0.5):
    """Clusters whose every sequence is mostly `X` -- poly-UNK depositions (e.g. 8gz3),
    which BLAST cannot score at all. They must not be silently counted as homology-clean."""
    cs = _manifest_cluster_split()
    bycl = collections.defaultdict(list)
    for s in seqs:
        if split not in s['splits']:
            continue
        xfrac = s['seq'].count('X') / max(1, s['len'])
        for c in s['clusters']:
            if cs.get(c) == split:
                bycl[c].append(xfrac)
    return sorted(c for c, v in bycl.items() if min(v) >= frac_x)


def _cluster_max(split, seqs, best, scored_clusters):
    """cluster -> max identity to any train sequence, over the cluster's own sequences."""
    cs = _manifest_cluster_split()
    out = {}
    for s in seqs:
        if split not in s['splits']:
            continue
        h = best.get(s['sid'])
        for c in s['clusters']:
            if cs.get(c) != split:
                continue
            if scored_clusters is not None and c not in scored_clusters:
                continue
            cur = out.setdefault(c, {'cluster': c, 'max_identity': 0.0, 'n_sequences': 0,
                                     'best_pair': None})
            cur['n_sequences'] += 1
            if h and h['cov_corrected_identity'] > cur['max_identity']:
                cur['max_identity'] = h['cov_corrected_identity']
                cur['best_pair'] = h
    return out


def _tier_table(cmax):
    n = len(cmax)
    rows = {}
    for t in TIERS:
        hit = [c for c, v in cmax.items() if v['max_identity'] >= t]
        rows[str(t)] = {'n_clusters_with_train_homolog': len(hit), 'of': n,
                        'pct': round(100 * len(hit) / n, 1) if n else None,
                        'n_clusters_clean': n - len(hit)}
    return rows


def phase_tier(args):
    seqs = json.loads((OUT / 'sequences.json').read_text())
    scored = json.loads((OUT / 'scored_clusters.json').read_text()) \
        if (OUT / 'scored_clusters.json').exists() else None
    res = {'identity_definition': {
        'coverage_corrected_identity': '100 * nident / min(qlen, slen), best single HSP',
        'raw_pident': "BLAST pident over the aligned region only (reported alongside)",
        'qualifying_hsp': (f'evalue <= {EVALUE_MAX} AND aln_length >= {MIN_ALN} AND '
                           f'aln_length >= {MIN_COV_FRAC} * min(qlen, slen); the '
                           f'{MIN_ALN}-column floor relaxes to {MIN_COV_FRAC} * shorter '
                           f'when the shorter sequence is < {MIN_ALN} aa'),
        'permissive_sensitivity_variant': (f'evalue <= {EVALUE_MAX} AND aln_length >= '
                                           f'{PERMISSIVE_MIN_ALN}, no coverage requirement'),
        'multi_hsp': 'best single HSP by coverage-corrected identity; HSPs never summed',
        'cluster_rule': ('a cluster max = max over its own chain sequences of the max over '
                         'all train-split chain sequences'),
        'tool_limitation': ('blastp only; mmseqs/HHsearch not available on this machine, so '
                            'the >=30% tier is a LOWER BOUND on true remote homology')}}
    for sp in ('test', 'val'):
        for mode, perm in (('strict', False), ('permissive', True)):
            best = _best_hits(OUT / f'{sp}_vs_train.tsv', seqs, permissive=perm)
            sc = set(scored[sp]) if scored and sp in scored else None
            cmax = _cluster_max(sp, seqs, best, sc)
            key = f'{sp}_{mode}'
            unj = [c for c in _unjudgeable(sp, seqs) if c in cmax]
            res[key] = {'n_clusters_evaluated': len(cmax),
                        'restricted_to_scored_clusters': sc is not None,
                        'unjudgeable_clusters_all_UNK_sequence': unj,
                        'n_unjudgeable': len(unj),
                        'tiers': _tier_table(cmax),
                        'identity_quantiles': {
                            q: round(float(np.percentile([v['max_identity'] for v in cmax.values()], q)), 1)
                            for q in (50, 75, 90, 95, 99)} if cmax else {},
                        'n_with_no_qualifying_hit': sum(1 for v in cmax.values()
                                                        if v['best_pair'] is None)}
            if mode == 'strict':
                write(OUT / f'cluster_max_identity_{sp}.json', cmax)
                write(OUT / f'unjudgeable_{sp}.json', unj)
                ex = collections.OrderedDict()
                band = [(100, 90), (90, 70), (70, 50), (50, 30)]
                for hi, lo in band:
                    sel = sorted([v for v in cmax.values() if lo <= v['max_identity'] < hi],
                                 key=lambda v: -v['max_identity'])[:args.examples]
                    ex[f'{lo}-{hi}'] = [{'test_cluster': v['cluster'],
                                         'identity': round(v['max_identity'], 1),
                                         'raw_pident': round(v['best_pair']['raw_pident'], 1),
                                         'aln_length': v['best_pair']['aln_length'],
                                         'qlen': v['best_pair']['qlen'],
                                         'slen': v['best_pair']['slen'],
                                         'evalue': v['best_pair']['evalue'],
                                         'test_chains': v['best_pair']['query_chains'],
                                         'train_chains': v['best_pair']['subject_chains'],
                                         'identical_modelled_sequence_in_train':
                                             v['best_pair']['query'] == v['best_pair']['subject'],
                                         'train_clusters': v['best_pair']['subject_clusters']}
                                        for v in sel]
                res[key]['examples_by_band'] = ex
    write(OUT / 'tier_table.json', res)
    print(json.dumps({k: (v if k == 'identity_definition'
                          else {kk: vv for kk, vv in v.items() if kk != 'examples_by_band'})
                      for k, v in res.items()}, indent=2))


# ---------------------------------------------------------------- phase: score

def _load_model():
    from xgboost import XGBClassifier
    m = XGBClassifier()
    m.load_model(str(MODEL))
    return m


def _per_cluster(rows, preds):
    """Per-cluster mean of each per-interface metric -- the unit score_rows macro-averages."""
    byc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, s in zip(rows, preds):
        order = S.nms(r['conflict'], s)
        maj = r['purity'] > .5
        for k in KS:
            top = order[:k]
            byc[r['cluster']][('majority_hit', k)].append(bool(np.any(maj[top])))
            byc[r['cluster']][('best_f1', k)].append(float(np.max(r['f1'][top])))
    return {c: {f'{m}@{k}': float(np.mean(v[(m, k)]))
                for m in ('majority_hit', 'best_f1') for k in KS}
            for c, v in byc.items()}


def phase_score(args):
    combo = ('geom', 'atom', 'esm')
    index = S.load_index(CACHE)
    test = [r for r in index if r['split'] == 'test' and S.patch_matrix(r['context'], ('geom',)) is not None]
    val = [r for r in index if r['split'] == 'val' and S.patch_matrix(r['context'], ('geom',)) is not None]
    model = _load_model()
    used, preds = S.predict(model, test, combo, 'patch_classifier')
    print(f'scored {len(used)} test interfaces, '
          f'{len(set(r["cluster"] for r in used))} clusters', flush=True)
    write(OUT / 'scored_clusters.json',
          {'test': sorted({r['cluster'] for r in used}),
           'val': sorted({r['cluster'] for r in val})})

    # Gate: the harness must reproduce the published numbers before any subset is believed.
    full = S.score_rows(used, preds)
    published = {'1': 0.32426809054508776, '3': 0.5084567668416484,
                 '5': 0.6325634690674531, '10': 0.7858394174498179}
    repro = {k: {'computed': full['majority_hit'][k], 'published': published[k],
                 'delta': full['majority_hit'][k] - published[k]} for k in published}
    ok = all(abs(v['delta']) < 1e-9 for v in repro.values())
    write(OUT / 'reproduction_check.json', {'reproduces_published_majority_hit': ok,
                                            'detail': repro, 'model_file': str(MODEL)})
    print('reproduction check:', 'PASS' if ok else 'FAIL',
          json.dumps({k: round(v['delta'], 12) for k, v in repro.items()}), flush=True)
    if not ok:
        print('STOPPING: harness does not reproduce the published test read.', flush=True)
        return

    percl = _per_cluster(used, preds)
    write(OUT / 'per_cluster_scores.json', percl)

    cmax = json.loads((OUT / 'cluster_max_identity_test.json').read_text())
    unj = set(json.loads((OUT / 'unjudgeable_test.json').read_text())) \
        if (OUT / 'unjudgeable_test.json').exists() else set()
    subsets = {'all_test': None}
    for t in (50, 30):
        clean = {c for c in percl if cmax.get(c, {}).get('max_identity', 0.0) < t}
        subsets[f'no_train_homolog_ge_{t}pct'] = clean
        if unj & clean:
            subsets[f'no_train_homolog_ge_{t}pct_judgeable_only'] = clean - unj
    res = {'model_file': str(MODEL), 'refit': False,
           'random_control_reps': RANDOM_REPS, 'subsets': {}}
    for name, keep in subsets.items():
        rows = [r for r in used if keep is None or r['cluster'] in keep]
        pr = [p for r, p in zip(used, preds) if keep is None or r['cluster'] in keep]
        nclus = len(set(r['cluster'] for r in rows))
        print(f'  {name}: {len(rows)} interfaces, {nclus} clusters -> scoring + control',
              flush=True)
        m = S.score_rows(rows, pr)
        rc = S.random_control(rows, reps=RANDOM_REPS, seed=S.SEED)
        blk = {'n_interfaces': len(rows), 'n_clusters': nclus,
               'majority_hit': {k: m['majority_hit'][k] for k in map(str, KS)},
               'best_f1': {k: m['best_f1'][k] for k in map(str, KS)},
               'half_epitope_recovery': {k: m['half_epitope_recovery'][k] for k in map(str, KS)},
               'oracle': m['oracle'],
               'random_control': {me: {k: rc[me][k] for k in map(str, KS)}
                                  for me in ('majority_hit', 'best_f1')},
               'lift_over_random': {me: {k: {'value': m[me][k],
                                             'random_mean': rc[me][k]['mean'],
                                             'random_sd': rc[me][k]['sd'],
                                             'lift': m[me][k] - rc[me][k]['mean'],
                                             'z': ((m[me][k] - rc[me][k]['mean']) / rc[me][k]['sd']
                                                   if rc[me][k]['sd'] else None)}
                                         for k in map(str, KS)}
                                    for me in ('majority_hit', 'best_f1')}}
        if nclus < 40:
            blk['caution'] = (f'only {nclus} clusters -- the cluster-macro CI is wide; quote '
                              f'the cluster count with the point estimate')
        res['subsets'][name] = blk
    write(OUT / 'subset_metrics.json', res)

    # ---- Spearman: is per-cluster performance explained by identity to train?
    from scipy.stats import spearmanr
    clusters = sorted(percl)
    ident = np.array([cmax.get(c, {}).get('max_identity', 0.0) for c in clusters])
    spear = {'n_clusters': len(clusters),
             'identity_is_zero_for_n_clusters': int((ident == 0).sum())}
    for key in [f'{m}@{k}' for m in ('majority_hit', 'best_f1') for k in KS]:
        y = np.array([percl[c][key] for c in clusters])
        rho, p = spearmanr(ident, y)
        spear[key] = {'spearman_rho': float(rho), 'p': float(p)}
        # Re-run excluding the identity==0 mass, which is a large tie block that can
        # dominate a rank correlation.
        nz = ident > 0
        if nz.sum() > 10:
            r2, p2 = spearmanr(ident[nz], y[nz])
            spear[key]['spearman_rho_nonzero_identity_only'] = float(r2)
            spear[key]['p_nonzero_identity_only'] = float(p2)
            spear[key]['n_nonzero'] = int(nz.sum())
    write(OUT / 'spearman_identity_vs_performance.json', spear)
    print(json.dumps(spear, indent=2))


BANDS = ((90, 101), (70, 90), (50, 70), (30, 50), (0, 30))


def phase_bands(args):
    """Stratify the test read by max-identity-to-train band, each with its own control.

    The cumulative `< t` subsets in phase `score` answer "does the headline survive".
    The bands answer the sharper question: does the model do *better* on the clusters that
    have a close training relative? A flat profile across bands is the strongest available
    evidence that performance is not homology-driven."""
    combo = ('geom', 'atom', 'esm')
    index = S.load_index(CACHE)
    test = [r for r in index if r['split'] == 'test'
            and S.patch_matrix(r['context'], ('geom',)) is not None]
    used, preds = S.predict(_load_model(), test, combo, 'patch_classifier')
    cmax = json.loads((OUT / 'cluster_max_identity_test.json').read_text())
    out = {'band_definition': 'max coverage-corrected identity to any train antigen chain',
           'random_control_reps': RANDOM_REPS, 'bands': {}}
    for lo, hi in BANDS:
        keep = {c for c in {r['cluster'] for r in used}
                if lo <= cmax.get(c, {}).get('max_identity', 0.0) < hi}
        rows = [r for r in used if r['cluster'] in keep]
        pr = [p for r, p in zip(used, preds) if r['cluster'] in keep]
        if not rows:
            out['bands'][f'{lo}-{hi}'] = {'n_clusters': 0, 'n_interfaces': 0}
            continue
        m = S.score_rows(rows, pr)
        rc = S.random_control(rows, reps=RANDOM_REPS, seed=S.SEED)
        out['bands'][f'{lo}-{hi}'] = {
            'n_clusters': len(keep), 'n_interfaces': len(rows),
            'majority_hit': {k: m['majority_hit'][k] for k in map(str, KS)},
            'best_f1': {k: m['best_f1'][k] for k in map(str, KS)},
            'oracle': m['oracle'],
            'random_control_majority_hit': {k: rc['majority_hit'][k] for k in map(str, KS)},
            'lift_majority_hit': {k: m['majority_hit'][k] - rc['majority_hit'][k]['mean']
                                  for k in map(str, KS)},
            'caution': ('cluster-macro CI is wide at this cluster count'
                        if len(keep) < 40 else None)}
        b = out['bands'][f'{lo}-{hi}']
        print(f"  band {lo}-{hi}: {len(keep):3d} clusters  maj@3 {b['majority_hit']['3']:.3f} "
              f"(chance {b['random_control_majority_hit']['3']['mean']:.3f}, "
              f"lift {b['lift_majority_hit']['3']:+.3f})", flush=True)
    write(OUT / 'identity_bands.json', out)


SABDAB2 = (DATA / "sabdab2")     # READ-ONLY
ARMS = (('ARM-1_their_test_partition', 'their test partition'),
        ('ARM-2_abag_cluster_clean', 'SAbDab2 ab-ag cluster never in our train'),
        ('ARM-3_antigen_cluster_clean', 'SAbDab2 ANTIGEN cluster never in our train (primary)'),
        ('ARM-4_intersection_2and3', 'intersection of ARM-2 and ARM-3'))
BOOT_REPS = 4000
CI_TOO_WIDE = 0.07      # +/- 7 macro points: wider than that and a bare point estimate misleads


def _bootstrap_ci(per_cluster_values, reps=BOOT_REPS, seed=S.SEED):
    """Percentile CI for a cluster-macro mean, resampling CLUSTERS with replacement.

    The macro mean is an average over clusters, so the clusters are the independent
    units and the cluster count -- not the interface count -- sets the width. This
    replaces an arbitrary 'too few clusters' threshold with a measured interval."""
    v = np.asarray(per_cluster_values, dtype=float)
    if len(v) < 2:
        return {'mean': float(v.mean()) if len(v) else None, 'ci95': None, 'half_width': None}
    rng = np.random.default_rng(seed)
    draws = v[rng.integers(0, len(v), size=(reps, len(v)))].mean(1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {'mean': float(v.mean()), 'ci95': [float(lo), float(hi)],
            'half_width': float((hi - lo) / 2), 'n_clusters': int(len(v))}


def _per_cluster_values(rows, preds):
    """cluster -> {metric@k: mean over that cluster's interfaces}; the macro summand."""
    byc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r, s in zip(rows, preds):
        order = S.nms(r['conflict'], s)
        maj = r['purity'] > .5
        half = r['coverage'] >= .5
        for k in KS:
            top = order[:k]
            byc[r['cluster']][('majority_hit', k)].append(bool(np.any(maj[top])))
            byc[r['cluster']][('half_epitope_recovery', k)].append(bool(np.any(half[top])))
            byc[r['cluster']][('best_f1', k)].append(float(np.max(r['f1'][top])))
    return {c: {f'{m}@{k}': float(np.mean(v[(m, k)]))
                for m in ('majority_hit', 'half_epitope_recovery', 'best_f1') for k in KS}
            for c, v in byc.items()}


def phase_arms(args):
    """Score externally-defined (SAbDab2) clean arms as subsets of our ALREADY-READ test
    split. This is stratification of one test read, not a new selection, so it spends no
    additional test-set budget under the pre-registered protocol. Nothing is refit."""
    combo = ('geom', 'atom', 'esm')
    index = S.load_index(CACHE)
    test = [r for r in index if r['split'] == 'test'
            and S.patch_matrix(r['context'], ('geom',)) is not None]
    used, preds = S.predict(_load_model(), test, combo, 'patch_classifier')
    bypred = dict(zip((r['id'] for r in used), preds))
    byrow = {r['id']: r for r in used}

    # Guard: the harness must still reproduce the published read before any arm is believed.
    full = S.score_rows(used, preds)
    published = {'1': 0.32426809054508776, '3': 0.5084567668416484,
                 '5': 0.6325634690674531, '10': 0.7858394174498179}
    deltas = {k: full['majority_hit'][k] - published[k] for k in published}
    if not all(abs(d) < 1e-9 for d in deltas.values()):
        print('STOPPING: harness no longer reproduces the published test read', deltas)
        return
    print('reproduction guard: PASS', flush=True)

    cmax = json.loads((OUT / 'cluster_max_identity_test.json').read_text())
    out = {'status': ('externally-defined arms scored as subsets of the single, already-read '
                      'test split; stratification, not re-selection; model loaded as saved'),
           'model_file': str(MODEL), 'refit': False,
           'external_split': {
               'source': 'SAbDab2 ML Dataset, Zenodo 10.5281/zenodo.22019991, CC-BY-4.0',
               'antigen_criterion': '40% Needleman-Wunsch identity + connected-component joining',
               'relation_to_our_split': ('coarser on the antigen side than cluster.py '
                                         '(accession OR exact sequence), so it is an '
                                         'independent external analogue of the BLAST-clean '
                                         'subsets in subset_metrics.json'),
               'arm_csv_dir': str(SABDAB2) + ' (read-only; not modified)'},
           'random_control_reps': RANDOM_REPS, 'bootstrap_reps': BOOT_REPS,
           'ci_too_wide_threshold_half_width': CI_TOO_WIDE,
           'macro_unit': 'our_cluster_id', 'arms': {}}

    arm_clusters = {}
    for stem, desc in ARMS:
        csv_path = SABDAB2 / f'{stem}.csv'
        ids, csv_clusters = [], set()
        with csv_path.open() as f:
            hdr = f.readline().rstrip('\n').split(',')
            ii, ci = hdr.index('instance_id'), hdr.index('our_cluster_id')
            for line in f:
                p = line.rstrip('\n').split(',')
                ids.append(p[ii])
                csv_clusters.add(p[ci])
        got = [i for i in ids if i in byrow]
        missing = [i for i in ids if i not in byrow]
        rows = [byrow[i] for i in got]
        pr = [bypred[i] for i in got]
        clusters = {r['cluster'] for r in rows}
        arm_clusters[stem] = clusters
        m = S.score_rows(rows, pr)
        rc = S.random_control(rows, reps=RANDOM_REPS, seed=S.SEED)
        percl = _per_cluster_values(rows, pr)
        boot = {f'{me}@{k}': _bootstrap_ci([percl[c][f'{me}@{k}'] for c in percl])
                for me in ('majority_hit', 'best_f1') for k in KS}
        wide = [key for key, b in boot.items()
                if b['half_width'] is not None and b['half_width'] > CI_TOO_WIDE]
        blk = {
            'description': desc, 'csv': str(csv_path),
            'instances_in_csv': len(ids), 'instances_scored': len(got),
            'instances_not_scorable': missing,
            'clusters_in_csv': len(csv_clusters), 'clusters_scored': len(clusters),
            'all_instances_in_our_test_split': all(byrow[i]['split'] == 'test' for i in got),
            'majority_hit': {k: m['majority_hit'][k] for k in map(str, KS)},
            'best_f1': {k: m['best_f1'][k] for k in map(str, KS)},
            'half_epitope_recovery': {k: m['half_epitope_recovery'][k] for k in map(str, KS)},
            'oracle': m['oracle'],
            'random_control': {me: {k: rc[me][k] for k in map(str, KS)}
                               for me in ('majority_hit', 'best_f1')},
            'lift_over_random': {me: {k: {'value': m[me][k],
                                          'random_mean': rc[me][k]['mean'],
                                          'random_sd': rc[me][k]['sd'],
                                          'lift': m[me][k] - rc[me][k]['mean'],
                                          'z': ((m[me][k] - rc[me][k]['mean']) / rc[me][k]['sd']
                                                if rc[me][k]['sd'] else None)}
                                      for k in map(str, KS)}
                                 for me in ('majority_hit', 'best_f1')},
            'cluster_bootstrap_ci95': boot,
            'ci_too_wide_to_quote_point_estimate': wide,
            'blast_identity_profile_of_this_arm': {
                str(t): sum(1 for c in clusters if cmax.get(c, {}).get('max_identity', 0.) >= t)
                for t in TIERS},
        }
        out['arms'][stem] = blk
        b3 = blk['cluster_bootstrap_ci95']['majority_hit@3']
        print(f"  {stem}: {len(got)}/{len(ids)} instances, {len(clusters)} clusters  "
              f"maj@3 {blk['majority_hit']['3']:.4f} "
              f"[{b3['ci95'][0]:.3f},{b3['ci95'][1]:.3f}] "
              f"chance {rc['majority_hit']['3']['mean']:.3f} "
              f"z={blk['lift_over_random']['majority_hit']['3']['z']:+.1f}"
              f"{'  CI-WIDE' if wide else ''}", flush=True)

    # ---- the cross-check: ARM-3 vs our own BLAST-clean subset
    ours = {c for c in {r['cluster'] for r in used}
            if cmax.get(c, {}).get('max_identity', 0.0) < 30}
    theirs = arm_clusters['ARM-3_antigen_cluster_clean']
    both, only_t, only_o = theirs & ours, theirs - ours, ours - theirs
    a3 = out['arms']['ARM-3_antigen_cluster_clean']
    mine = json.loads((OUT / 'subset_metrics.json').read_text())['subsets']['no_train_homolog_ge_30pct']
    d3 = a3['majority_hit']['3'] - mine['majority_hit']['3']
    sd_t = a3['random_control']['majority_hit']['3']['sd']
    sd_o = mine['random_control']['majority_hit']['3']['sd']
    pooled = float(np.hypot(sd_t, sd_o))

    def ident(cs):
        v = [cmax.get(c, {}).get('max_identity', 0.0) for c in cs]
        return {'n': len(v),
                'median_blast_identity_to_train': round(float(np.median(v)), 1) if v else None,
                'n_ge_30pct': sum(1 for x in v if x >= 30),
                'n_ge_50pct': sum(1 for x in v if x >= 50),
                'n_ge_90pct': sum(1 for x in v if x >= 90)}

    out['cross_check_arm3_vs_our_blast_clean'] = {
        'our_subset': 'no_train_homolog_ge_30pct (BLAST, coverage-corrected, this audit)',
        'their_subset': 'ARM-3 (SAbDab2 antigen cluster never in our train, 40% NW + CC)',
        'n_our': len(ours), 'n_theirs': len(theirs),
        'n_intersection': len(both),
        'n_theirs_only': len(only_t), 'n_ours_only': len(only_o),
        'jaccard': round(len(both) / len(theirs | ours), 3),
        'our_maj_hit_at_3': mine['majority_hit']['3'],
        'their_maj_hit_at_3': a3['majority_hit']['3'],
        'difference': d3,
        'control_sd_theirs': sd_t, 'control_sd_ours': sd_o,
        'pooled_control_sd': pooled,
        'agree_within_pooled_control_sd': bool(abs(d3) <= pooled),
        'agree_within_either_control_sd': bool(abs(d3) <= max(sd_t, sd_o)),
        'our_bootstrap_ci95_maj3': _bootstrap_ci(
            [v['majority_hit@3'] for c, v in
             _per_cluster_values([r for r in used if r['cluster'] in ours],
                                 [p for r, p in zip(used, preds) if r['cluster'] in ours]).items()]),
        'their_bootstrap_ci95_maj3': a3['cluster_bootstrap_ci95']['majority_hit@3'],
        'disagreement_profile': {
            'theirs_only': ident(only_t), 'ours_only': ident(only_o),
            'intersection': ident(both),
            'interpretation': ('theirs_only clusters are ones BLAST calls homologous (>=30%) '
                               'but SAbDab2 40%-NW clustering does not join to train -- the '
                               'two criteria differ most in the 30-50% twilight zone'),
            'theirs_only_clusters': sorted(only_t), 'ours_only_clusters': sorted(only_o)},
    }
    cc = out['cross_check_arm3_vs_our_blast_clean']
    print(f"\ncross-check: ARM-3 {len(theirs)} clusters vs ours {len(ours)}; "
          f"intersection {len(both)} (Jaccard {cc['jaccard']}); "
          f"maj@3 {cc['their_maj_hit_at_3']:.4f} vs {cc['our_maj_hit_at_3']:.4f} "
          f"(delta {d3:+.4f}, pooled control sd {pooled:.4f}, "
          f"agree={cc['agree_within_pooled_control_sd']})", flush=True)
    write(OUT / 'sabdab2_arm_metrics.json', out)
    print(f"wrote {OUT / 'sabdab2_arm_metrics.json'}")


def phase_report(_args):
    """Merge every receipt into the single defensible artifact."""
    def rd(n):
        p = OUT / n
        return json.loads(p.read_text()) if p.exists() else None
    tier = rd('tier_table.json')
    art = {
        'title': 'PRINCE antigen split: remote-homology audit and homology-clean rescore',
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'question': ('cluster.py joins antigen chains on UniProt accession OR exact sequence '
                     'only, so test clusters may still hold close homologues of train '
                     'antigens. How much, and does the headline survive removing them?'),
        'inputs': {
            'manifest': str(MANIFEST),
            'manifest_rows': 6937,
            'splits_instances': {'train': 4760, 'val': 1057, 'test': 1120},
            'splits_clusters': {'train': 1065, 'val': 233, 'test': 251},
            'structure_cache': str(CACHE),
            'locked_model': str(MODEL),
            'model_was_refit_here': False,
            'blast': 'ncbi blast+ makeblastdb/blastp at /usr/local/bin (mmseqs unavailable)'},
        'sequence_receipt': rd('sequence_receipt.json'),
        'identity_definition': tier['identity_definition'] if tier else None,
        'tier_table': {k: v for k, v in (tier or {}).items() if k != 'identity_definition'},
        'reproduction_check': rd('reproduction_check.json'),
        'subset_metrics': rd('subset_metrics.json'),
        'identity_bands': rd('identity_bands.json'),
        'spearman_identity_vs_performance': rd('spearman_identity_vs_performance.json'),
        'script_sha256': S.digest(__file__),
        'artifacts_dir': str(OUT)}
    write(OUT / 'split_audit.json', art)
    print(f"wrote {OUT / 'split_audit.json'}")


def phase_all(args):
    phase_seq(args)
    phase_blast(args)
    # tier needs scored_clusters.json from score, and score needs cluster_max from tier;
    # break the cycle by tiering unrestricted first, scoring, then re-tiering restricted.
    phase_tier(args)
    phase_score(args)
    phase_tier(args)
    phase_score(args)
    phase_bands(args)
    phase_report(args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', required=True,
                    choices=['seq', 'blast', 'tier', 'score', 'bands', 'arms', 'report', 'all'])
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--examples', type=int, default=6)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {'seq': phase_seq, 'blast': phase_blast, 'tier': phase_tier, 'score': phase_score,
     'bands': phase_bands, 'arms': phase_arms, 'report': phase_report,
     'all': phase_all}[args.phase](args)


if __name__ == '__main__':
    main()
