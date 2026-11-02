"""Is the PRINCE benchmark's epitope-negative label trustworthy, or just under-sampled?

Answers a reviewer criticism (SAbDab maintainer): a surface residue not seen in an
antibody complex may still be targetable, so "negative" may mean "nobody crystallised
a binder there yet". Four measurements:

  1. sampling completeness -- per antigen cluster: instances, DISTINCT antibodies
     (blastp single-linkage on heavy and light chains separately), epitope union across
     all its entries, and what fraction of the modelled exposed surface that union covers.
  2. does the headline depend on under-sampling -- the LOCKED model (reloaded, never
     refit) re-read on test, stratified by sampling depth, plus a union-epitope variant
     where an instance is scored against every epitope ever seen on that antigen.
  3. chaperone / reference-antibody flagging -- antibodies recurring across unrelated
     antigen clusters, and the headline with them removed.
  4. verdict (written by hand from these numbers, not by this script).

Cross-entry epitope union needs a residue correspondence between entries of the same
cluster: antigen chain sequences are grouped by identity and aligned to the longest
member with difflib exact matching blocks, so only unambiguous positions carry a label.

Stages, run serially (disk and swap are tight):
  seqs -> abclust -> prep -> align -> metrics -> report
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, collections, csv, difflib, gzip, hashlib, json, os, pickle, subprocess, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sweep as S  # noqa: E402  (score_rows / nms / patch_matrix / predict)

CACHE = (DATA / "cache_all")
RCSB = (DATA / "benchmark/rcsb")
MANIFEST = (REPO / "data/eval/prince_connected.manifest.csv")
LOCKED = MODEL
OUT = (DATA / "label_sampling"); OUT.mkdir(parents=True, exist_ok=True)

KS = (1, 3, 5, 10)
RSA_EXPOSED = 0.20           # primary "solvent-exposed" definition (relative SASA)
RSA_SENSITIVITY = (0.05, 0.25)
AB_PIDENT = 95.0             # blastp identity for "same antibody chain"
AB_COVER = 0.80              # aligned length / shorter chain
CHAIN_GROUP_RATIO = 0.90     # antigen chain-sequence identity to share a coordinate frame
RANDOM_REPS = 200
SEED = 17
AA3 = ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE', 'LEU', 'LYS',
       'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL', 'UNK']
AA1 = 'ARNDCQEGHILKMFPSTWYVX'
RSA_COL = 4                  # feature_names[4] == 'relative_sasa'
AA_COL0 = 6                  # feature_names[6:27] == aa_ALA .. aa_UNK


def jdump(p, d):
    Path(p).write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


# ------------------------------------------------------------------ stage: seqs

def stage_seqs(_):
    """Per-instance antibody heavy/light sequences, pulled from the local RCSB mirror."""
    rows = list(csv.DictReader(MANIFEST.open()))
    ent_cache: dict[str, dict[str, str]] = {}
    inst, miss = {}, collections.Counter()
    for r in rows:
        p = r['pdb_id']
        if p not in ent_cache:
            m = {}
            for e in json.loads((RCSB / f'{p}.json').read_text()):
                seq = e['entity_poly']['pdbx_seq_one_letter_code_can']
                for c in e['rcsb_polymer_entity_container_identifiers']['auth_asym_ids']:
                    m[c] = seq
            ent_cache[p] = m
        m = ent_cache[p]
        h, l = r['heavy_chain'].strip(), r['light_chain'].strip()

        def look(c):
            """SAbDab2 splits single-chain Fvs into pseudo-chains ('A1'/'A2'); RCSB only
            knows the parent auth asym id, so fall back to the digit-stripped id."""
            if not c:
                return '', ''
            if c in m:
                return m[c], 'exact'
            s = c.rstrip('0123456789')
            if s and s in m:
                return m[s], 'digit_stripped'
            return '', 'failed'
        hs, hk = look(h)
        ls, lk = look(l)
        miss[f'heavy_{hk}'] += 1 if h else 0
        miss[f'light_{lk}'] += 1 if l else 0
        inst[r['instance_id']] = {'pdb': p, 'h_chain': h, 'l_chain': l,
                                  'h': hs, 'l': ls, 'cluster': r['cluster_id'],
                                  'split': r['split']}
        if len(ent_cache) > 400:
            ent_cache.clear()
    uh = sorted({v['h'] for v in inst.values() if v['h']})
    ul = sorted({v['l'] for v in inst.values() if v['l']})
    jdump(OUT / 'ab_sequences.json',
          {'n_instances': len(inst), 'unique_heavy': len(uh), 'unique_light': len(ul),
           'chain_sequence_lookup_failures': dict(miss), 'instances': inst})
    for tag, seqs in (('heavy', uh), ('light', ul)):
        with (OUT / f'{tag}.fasta').open('w') as f:
            for i, s in enumerate(seqs):
                f.write(f'>{tag[0]}{i}\n{s}\n')
    print(f'{len(inst)} instances; {len(uh)} unique heavy, {len(ul)} unique light; '
          f'lookup failures {dict(miss)}')


# --------------------------------------------------------------- stage: abclust

def _single_linkage(n, edges):
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return [find(i) for i in range(n)]


def _complete_linkage(members, pid, thresh):
    """Proper complete-linkage clustering of one connected component.

    Antibody V-regions are germline-constrained: two unrelated human heavy chains
    routinely share >90% framework identity, so SINGLE linkage at 95% chains distinct
    antibodies into one cluster through a path of near neighbours (measured: a single
    component held 36 heavy sequences with pairwise identity as low as 0.48). Complete
    linkage requires every pair inside a cluster to clear the threshold.
    """
    n = len(members)
    if n == 1:
        return [0]
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    D = np.ones((n, n), dtype=float)
    np.fill_diagonal(D, 0.0)
    for i in range(n):
        for j in range(i + 1, n):
            p = pid.get((members[i], members[j]), pid.get((members[j], members[i])))
            if p is not None:
                D[i, j] = D[j, i] = max(0.0, 1.0 - p / 100.0)
    Z = linkage(squareform(D, checks=False), method='complete')
    return list(fcluster(Z, t=1.0 - thresh / 100.0, criterion='distance'))


def _blast_cluster(fasta, tag):
    db = OUT / f'{tag}_db'
    subprocess.run(['/usr/local/bin/makeblastdb', '-in', str(fasta), '-dbtype', 'prot',
                    '-out', str(db)], check=True, capture_output=True)
    hits = OUT / f'{tag}_selfhits.tsv'
    subprocess.run(['/usr/local/bin/blastp', '-query', str(fasta), '-db', str(db),
                    '-outfmt', '6 qseqid sseqid pident length qlen slen',
                    '-evalue', '1e-5', '-max_target_seqs', '5000', '-num_threads', '4',
                    '-out', str(hits)], check=True, capture_output=True)
    names = [l[1:].strip() for l in fasta.read_text().splitlines() if l.startswith('>')]
    idx = {n: i for i, n in enumerate(names)}
    edges, pid_of = [], {}
    with hits.open() as f:
        for line in f:
            q, s, pid, alen, ql, sl = line.split('\t')
            if q == s:
                continue
            if int(alen) >= AB_COVER * min(int(ql), int(sl)):
                a, b = idx[q], idx[s]
                pid_of[(a, b)] = max(pid_of.get((a, b), 0.0), float(pid))
                if float(pid) >= AB_PIDENT:
                    edges.append((a, b))
    hits.unlink()
    # single linkage first (cheap component finder), then complete linkage inside each
    roots = _single_linkage(len(names), edges)
    comps = collections.defaultdict(list)
    for i, r in enumerate(roots):
        comps[r].append(i)
    out, n_clu = {}, 0
    chained = 0
    for r, members in sorted(comps.items()):
        sub = _complete_linkage(members, pid_of, AB_PIDENT)
        local = {}
        for m, s in zip(members, sub):
            if s not in local:
                local[s] = f'{tag[0]}c{n_clu}'
                n_clu += 1
            out[names[m]] = local[s]
        if len(local) > 1:
            chained += 1
    print(f'{tag}: {len(names)} unique sequences -> {len(comps)} single-linkage components '
          f'-> {n_clu} complete-linkage clusters at {AB_PIDENT}% ({chained} components split)')
    return out


def stage_abclust(_):
    meta = json.loads((OUT / 'ab_sequences.json').read_text())
    hmap = _blast_cluster(OUT / 'heavy.fasta', 'heavy')
    lmap = _blast_cluster(OUT / 'light.fasta', 'light')
    useq_h = {}
    for l in (OUT / 'heavy.fasta').read_text().split('>')[1:]:
        n, s = l.split('\n', 1)
        useq_h[s.strip()] = hmap[n.strip()]
    useq_l = {}
    for l in (OUT / 'light.fasta').read_text().split('>')[1:]:
        n, s = l.split('\n', 1)
        useq_l[s.strip()] = lmap[n.strip()]
    ab = {}
    for iid, v in meta['instances'].items():
        hc = useq_h.get(v['h'], 'hNONE')
        lc = useq_l.get(v['l'], 'lNONE')
        ab[iid] = f'{hc}|{lc}'
    jdump(OUT / 'ab_clusters.json',
          {'heavy_identity_pct': AB_PIDENT, 'coverage_of_shorter_chain': AB_COVER,
           'method': 'blastp all-vs-all, COMPLETE-linkage (every pair in a cluster >= '
                     f'{AB_PIDENT}% identity over >= {AB_COVER:.0%} of the shorter chain) on '
                     'heavy and on light separately; antibody identity = (heavy cluster, '
                     'light cluster); light cluster "lNONE" = single-domain / no light chain. '
                     'Single linkage was tried first and rejected: it chained unrelated '
                     'antibodies together through conserved framework identity.',
           'n_unique_heavy_clusters': len(set(hmap.values())),
           'n_unique_light_clusters': len(set(lmap.values())),
           'n_distinct_antibodies': len(set(ab.values())),
           'instance_to_antibody': ab})
    print(f'{len(set(ab.values()))} distinct antibodies over {len(ab)} instances')


# ------------------------------------------------------------------ stage: prep

def stage_prep(_):
    """Compact per-context dump: residue identity, RSA, patch pool, instances."""
    ctxs = {}
    t0 = time.monotonic()
    files = sorted(CACHE.glob('*.json.gz'))
    for i, f in enumerate(files, 1):
        with gzip.open(f, 'rt') as s:
            o = json.load(s)
        if not o['patches']:
            continue
        F = np.asarray(o['features'], dtype=np.float32)
        assert o['feature_names'][RSA_COL] == 'relative_sasa'
        assert o['feature_names'][AA_COL0] == 'aa_ALA' and o['feature_names'][AA_COL0 + 20] == 'aa_UNK'
        aa_i = np.argmax(F[:, AA_COL0:AA_COL0 + 21], axis=1)
        ctxs[o['context_id']] = {
            'pdb': o['pdb'],
            'chain_of': [k.split(':')[0] for k in o['keys']],
            'display_keys': list(o['display_keys']),
            'aa': ''.join(AA1[j] for j in aa_i),
            'rsa': F[:, RSA_COL].astype(np.float32),
            'patches': [np.asarray(p['indices'], dtype=np.int32) for p in o['patches']],
            'instances': [{'id': x['id'], 'cluster': x['cluster'], 'split': x['split'],
                           'epitope': list(x['epitope'])} for x in o['instances']],
        }
        if i % 1000 == 0:
            print(f'{i}/{len(files)} {i/(time.monotonic()-t0):.0f} ctx/s', flush=True)
    with (OUT / 'contexts.pkl').open('wb') as f:
        pickle.dump(ctxs, f, protocol=4)
    print(f'prepped {len(ctxs)} contexts -> {(OUT/"contexts.pkl").stat().st_size/1e6:.0f} MB')


# ----------------------------------------------------------------- stage: align

def _chain_slices(c):
    """[(chain, [row indices in context order])] for one context."""
    out = collections.OrderedDict()
    for i, ch in enumerate(c['chain_of']):
        out.setdefault(ch, []).append(i)
    return list(out.items())


def stage_align(_):
    with (OUT / 'contexts.pkl').open('rb') as f:
        ctxs = pickle.load(f)
    ab = json.loads((OUT / 'ab_clusters.json').read_text())['instance_to_antibody']
    dom_chain = {r['instance_id']: r['dominant_chain'] for r in csv.DictReader(MANIFEST.open())}

    by_cluster = collections.defaultdict(set)
    inst_ctx = {}
    for cid, c in ctxs.items():
        for inst in c['instances']:
            by_cluster[inst['cluster']].add(cid)
            inst_ctx[inst['id']] = cid

    union_labels = {}        # instance id -> set of display_keys (cluster-union epitope)
    completeness = {}
    ref_seqs = {}            # cluster -> dominant-chain reference sequence
    align_stats = collections.Counter()
    for n_done, (clu, ctx_ids) in enumerate(sorted(by_cluster.items()), 1):
        ctx_ids = sorted(ctx_ids)
        # --- group this cluster's antigen chains into shared coordinate frames
        items = []           # (len, ctx_id, chain, seq, rows)
        for cid in ctx_ids:
            c = ctxs[cid]
            for ch, rows in _chain_slices(c):
                items.append((len(rows), cid, ch, ''.join(c['aa'][i] for i in rows), rows))
        items.sort(key=lambda x: -x[0])
        groups = []          # [{'rep': (cid, ch, seq, rows), 'members': [...]}]
        group_of_chain = {}  # (ctx_id, chain) -> group index
        for L, cid, ch, seq, rows in items:
            placed = False
            for gi, g in enumerate(groups):
                if difflib.SequenceMatcher(None, seq, g['rep'][2], autojunk=False).ratio() >= CHAIN_GROUP_RATIO:
                    g['members'].append((cid, ch, seq, rows))
                    group_of_chain[(cid, ch)] = gi
                    placed = True
                    break
            if not placed:
                group_of_chain[(cid, ch)] = len(groups)
                groups.append({'rep': (cid, ch, seq, rows), 'members': [(cid, ch, seq, rows)]})
        # --- residue -> (group, reference index) map
        loc2ref = {}         # (ctx_id, row index) -> (gi, ref row index)
        for gi, g in enumerate(groups):
            rcid, rch, rseq, rrows = g['rep']
            for cid, ch, seq, rows in g['members']:
                if cid == rcid and ch == rch:
                    blocks = [(0, 0, len(seq))]
                else:
                    sm = difflib.SequenceMatcher(None, seq, rseq, autojunk=False)
                    blocks = [(b.a, b.b, b.size) for b in sm.get_matching_blocks() if b.size]
                mapped = 0
                for a, b, size in blocks:
                    for d in range(size):
                        loc2ref[(cid, rows[a + d])] = (gi, rrows[b + d])
                        mapped += 1
                align_stats['residues'] += len(rows)
                align_stats['residues_mapped'] += mapped
        # --- epitope union in reference coordinates
        union_ref = set()
        n_inst, abs_seen, ep_per_inst = 0, set(), []
        dom_votes = collections.Counter()
        for cid in ctx_ids:
            c = ctxs[cid]
            pos = {k: i for i, k in enumerate(c['display_keys'])}
            for inst in c['instances']:
                if inst['cluster'] != clu:
                    continue
                n_inst += 1
                abs_seen.add(ab.get(inst['id'], 'UNKNOWN'))
                ep_per_inst.append(len(inst['epitope']))
                gi = group_of_chain.get((cid, dom_chain.get(inst['id'], '')))
                if gi is not None:
                    dom_votes[gi] += 1
                for k in inst['epitope']:
                    r = loc2ref.get((cid, pos[k]))
                    if r is not None:
                        union_ref.add(r)
                    else:
                        align_stats['epitope_residues_unmapped'] += 1
        # --- project the union back onto every instance's own numbering
        for cid in ctx_ids:
            c = ctxs[cid]
            back = set()
            for i in range(len(c['display_keys'])):
                r = loc2ref.get((cid, i))
                if r is not None and r in union_ref:
                    back.add(c['display_keys'][i])
            for inst in c['instances']:
                if inst['cluster'] == clu:
                    union_labels[inst['id']] = back
        # --- exposed-surface coverage, on the reference residues only.
        # "dominant" = the chain group holding the manifest's dominant antigen chain for
        # most of the cluster's instances -- i.e. the chain the antibodies actually bind,
        # not merely the longest chain present in the entry.
        dom_gi = dom_votes.most_common(1)[0][0] if dom_votes else 0
        ref_seqs[clu] = groups[dom_gi]['rep'][2]

        def frac(thresh, only_dominant):
            gl = [dom_gi] if only_dominant else range(len(groups))
            exp = lab = 0
            for gi in gl:
                rcid, rch, rseq, rrows = groups[gi]['rep']
                rsa = ctxs[rcid]['rsa']
                for r in rrows:
                    if rsa[r] >= thresh:
                        exp += 1
                        if (gi, r) in union_ref:
                            lab += 1
            return exp, lab
        e_all, l_all = frac(RSA_EXPOSED, False)
        e_dom, l_dom = frac(RSA_EXPOSED, True)
        sens = {}
        for t in RSA_SENSITIVITY:
            e, l = frac(t, True)
            sens[str(t)] = {'n_exposed': e, 'n_labelled': l, 'frac': round(l / e, 5) if e else None}
        completeness[clu] = {
            'n_instances': n_inst,
            'n_distinct_antibodies': len(abs_seen),
            'n_pdb_entries': len({ctxs[c]['pdb'] for c in ctx_ids}),
            'n_contexts': len(ctx_ids),
            'n_chain_groups': len(groups),
            'splits': sorted({i['split'] for c in ctx_ids for i in ctxs[c]['instances']
                              if i['cluster'] == clu}),
            'mean_epitope_size': round(float(np.mean(ep_per_inst)), 2),
            'n_union_epitope_residues': len(union_ref),
            'dominant_group': {'n_exposed': e_dom, 'n_labelled': l_dom,
                               'frac_exposed_labelled': round(l_dom / e_dom, 5) if e_dom else None},
            'all_chain_groups': {'n_exposed': e_all, 'n_labelled': l_all,
                                 'frac_exposed_labelled': round(l_all / e_all, 5) if e_all else None},
            'sensitivity_rsa': sens,
        }
        if n_done % 200 == 0:
            print(f'{n_done}/{len(by_cluster)} clusters aligned', flush=True)

    with (OUT / 'union_labels.pkl').open('wb') as f:
        pickle.dump(union_labels, f, protocol=4)
    names = sorted(ref_seqs)
    with (OUT / 'antigen_ref.fasta').open('w') as f:
        for i, clu in enumerate(names):
            f.write(f'>ag{i}\n{ref_seqs[clu]}\n')
    jdump(OUT / 'antigen_ref_names.json', {f'ag{i}': clu for i, clu in enumerate(names)})
    jdump(OUT / 'sampling_completeness.json',
          {'rsa_exposed_threshold': RSA_EXPOSED,
           'chain_group_identity_ratio': CHAIN_GROUP_RATIO,
           'alignment': dict(align_stats),
           'n_clusters': len(completeness), 'clusters': completeness})
    print(f'aligned {len(completeness)} clusters; alignment {dict(align_stats)}')


# ------------------------------------------------------------ stage: antigenhom

AG_EVALUE = '1e-10'
AG_MIN_COVER = 0.50


def stage_antigenhom(_):
    """Group antigen CLUSTERS into homology components.

    The benchmark's clusters are sequence-identity components, so two strains of one
    variable antigen (HIV Env, influenza HA) are different clusters. Without this step
    a broadly neutralising antibody is indistinguishable from a crystallisation
    chaperone -- both "recur across many clusters".
    """
    fasta = OUT / 'antigen_ref.fasta'
    db = OUT / 'ag_db'
    subprocess.run(['/usr/local/bin/makeblastdb', '-in', str(fasta), '-dbtype', 'prot',
                    '-out', str(db)], check=True, capture_output=True)
    hits = OUT / 'ag_selfhits.tsv'
    subprocess.run(['/usr/local/bin/blastp', '-query', str(fasta), '-db', str(db),
                    '-outfmt', '6 qseqid sseqid pident length qlen slen evalue',
                    '-evalue', AG_EVALUE, '-max_target_seqs', '3000', '-num_threads', '4',
                    '-out', str(hits)], check=True, capture_output=True)
    names = [l[1:].strip() for l in fasta.read_text().splitlines() if l.startswith('>')]
    idx = {n: i for i, n in enumerate(names)}
    edges = []
    with hits.open() as f:
        for line in f:
            q, s, pid, alen, ql, sl, ev = line.split('\t')
            if q != s and int(alen) >= AG_MIN_COVER * min(int(ql), int(sl)):
                edges.append((idx[q], idx[s]))
    roots = _single_linkage(len(names), edges)
    nm = json.loads((OUT / 'antigen_ref_names.json').read_text())
    remap, comp = {}, {}
    for n, r in zip(names, roots):
        comp[nm[n]] = remap.setdefault(r, f'ag_comp{len(remap)}')
    hits.unlink()
    jdump(OUT / 'antigen_homology.json',
          {'criterion': f'blastp evalue<={AG_EVALUE}, aligned length >= {AG_MIN_COVER:.0%} '
                        'of the shorter sequence, single-linkage over cluster '
                        'dominant-chain reference sequences',
           'n_clusters': len(comp), 'n_homology_components': len(remap),
           'cluster_to_component': comp})
    print(f'{len(comp)} antigen clusters -> {len(remap)} homology components')


# --------------------------------------------------------------- stage: metrics

def _index(union_labels=None):
    """sweep.load_index, but optionally relabelled with the cluster-union epitope."""
    with (OUT / 'contexts.pkl').open('rb') as f:
        ctxs = pickle.load(f)
    out = []
    for cid, c in ctxs.items():
        pat = c['patches']
        sizes = np.asarray([len(p) for p in pat])
        memb = np.zeros((len(pat), len(c['display_keys'])), dtype=bool)
        for i, p in enumerate(pat):
            memb[i, p] = True
        I = memb.astype(np.int16) @ memb.astype(np.int16).T
        U = sizes[:, None] + sizes[None, :] - I
        conflict = (I / np.maximum(U, 1)) >= .5
        np.fill_diagonal(conflict, False)
        disp = c['display_keys']
        for inst in c['instances']:
            pos = set(union_labels[inst['id']]) if union_labels is not None else set(inst['epitope'])
            y = np.fromiter((d in pos for d in disp), dtype=bool, count=len(disp))
            if union_labels is None and y.sum() != len(pos):
                raise ValueError(f'label identity lost for {inst["id"]}')
            inter = np.asarray([int(y[p].sum()) for p in pat])
            purity = inter / sizes
            coverage = inter / max(1, int(y.sum()))
            with np.errstate(divide='ignore', invalid='ignore'):
                f1 = np.nan_to_num(np.where(purity + coverage > 0,
                                            2 * purity * coverage / (purity + coverage), 0.0))
            out.append({'id': inst['id'], 'context': cid, 'split': inst['split'],
                        'cluster': inst['cluster'], 'n_patches': len(pat),
                        'n_label': int(y.sum()),
                        'purity': purity.astype(np.float32),
                        'coverage': coverage.astype(np.float32),
                        'f1': f1.astype(np.float32), 'conflict': conflict})
    return out


def _table(rows, preds, label, reps=RANDOM_REPS):
    m = S.score_rows(rows, preds, with_oracle=True)
    ctrl = S.random_control(rows, reps=reps, seed=SEED)
    return {'label': label, 'n_interfaces': len(rows),
            'n_clusters': len(set(r['cluster'] for r in rows)),
            'majority_hit': {str(k): round(m['majority_hit'][str(k)], 4) for k in KS},
            'best_f1': {str(k): round(m['best_f1'][str(k)], 4) for k in KS},
            'half_epitope_recovery': {str(k): round(m['half_epitope_recovery'][str(k)], 4) for k in KS},
            'oracle': {k: round(v, 4) for k, v in m['oracle'].items()},
            'random_control_reps': reps,
            'random_majority_hit': {str(k): {'mean': round(ctrl['majority_hit'][str(k)]['mean'], 4),
                                             'sd': round(ctrl['majority_hit'][str(k)]['sd'], 4)} for k in KS},
            'random_best_f1': {str(k): {'mean': round(ctrl['best_f1'][str(k)]['mean'], 4),
                                        'sd': round(ctrl['best_f1'][str(k)]['sd'], 4)} for k in KS}}


def stage_metrics(_):
    from xgboost import XGBClassifier
    lock = json.loads((DATA / 'sweep_lock.json').read_text())
    combo = tuple(lock['config']['combo'])
    model = XGBClassifier()
    model.load_model(str(LOCKED))

    comp = json.loads((OUT / 'sampling_completeness.json').read_text())['clusters']
    ab = json.loads((OUT / 'ab_clusters.json').read_text())['instance_to_antibody']
    with (OUT / 'union_labels.pkl').open('rb') as f:
        union_labels = pickle.load(f)

    res = {'locked_model': lock['winner'], 'model_file': str(LOCKED), 'refit': False}

    # ---- chaperone / reference-antibody detection (needs no model)
    hom = json.loads((OUT / 'antigen_homology.json').read_text())
    clu2comp = hom['cluster_to_component']
    ab_inst = collections.defaultdict(list)
    with (OUT / 'contexts.pkl').open('rb') as f:
        ctxs = pickle.load(f)
    inst_meta = {}
    for cid, c in ctxs.items():
        for inst in c['instances']:
            inst_meta[inst['id']] = {'cluster': inst['cluster'], 'split': inst['split'], 'pdb': c['pdb']}
    del ctxs
    spread = collections.defaultdict(set)    # antibody -> antigen CLUSTERS
    hspread = collections.defaultdict(set)   # antibody -> antigen HOMOLOGY components
    for iid, a in ab.items():
        if iid in inst_meta:
            clu = inst_meta[iid]['cluster']
            spread[a].add(clu)
            hspread[a].add(clu2comp.get(clu, clu))
            ab_inst[a].append(iid)
    recurring = sorted(((len(v), a) for a, v in hspread.items()), reverse=True)
    top = []
    for n, a in recurring[:30]:
        ids = sorted(ab_inst[a])
        top.append({'antibody': a,
                    'n_unrelated_antigens': n,
                    'n_distinct_antigen_clusters': len(spread[a]),
                    'n_instances': len(ids),
                    'n_test_instances': sum(1 for i in ids if inst_meta[i]['split'] == 'test'),
                    'has_light_chain': not a.endswith('|lNONE'),
                    'pdb_ids': sorted({inst_meta[i]['pdb'] for i in ids}),
                    'antigen_components': sorted(hspread[a])})
    res['recurring_antibodies'] = {
        'definition': f'antibody = (heavy cluster, light cluster) at {AB_PIDENT}% identity / '
                      f'{AB_COVER:.0%} coverage. "n_unrelated_antigens" counts antigen '
                      'HOMOLOGY COMPONENTS, so strains of one variable antigen (a bnAb target) '
                      'count once; "n_distinct_antigen_clusters" is the raw benchmark-cluster count.',
        'n_antibodies': len(spread),
        'by_unrelated_antigens': {
            f'ge{t}': sum(1 for v in hspread.values() if len(v) >= t) for t in (2, 3, 5, 10)},
        'by_raw_clusters': {
            f'ge{t}': sum(1 for v in spread.values() if len(v) >= t) for t in (2, 3, 5, 10)},
        'top': top}

    # ---- test reads
    idx = _index(None)
    test = [r for r in idx if r['split'] == 'test' and S.patch_matrix(r['context'], ('geom',)) is not None]
    used, preds = S.predict(model, test, combo, lock['config']['kind'])
    pred_by_id = {r['id']: p for r, p in zip(used, preds)}
    res['all_test'] = _table(used, preds, 'all test clusters')
    head = res['all_test']['majority_hit']
    expect = {'1': 0.3243, '3': 0.5085, '5': 0.6326, '10': 0.7858}
    res['reproduction_check'] = {'expected': expect, 'observed': head,
                                 'ok': all(abs(head[k] - v) <= 0.0015 for k, v in expect.items())}
    print('reproduction check:', res['reproduction_check'], flush=True)
    if not res['reproduction_check']['ok']:
        jdump(OUT / 'metrics.json', res)
        print('HARNESS NOT REPRODUCING -- stopping', file=sys.stderr)
        return

    depth = {c: comp[c]['n_distinct_antibodies'] for c in comp}
    for lo, name in ((3, 'well_sampled_ge3_antibodies'), (5, 'well_sampled_ge5_antibodies')):
        sub = [r for r in used if depth.get(r['cluster'], 0) >= lo]
        res[name] = _table(sub, [pred_by_id[r['id']] for r in sub],
                           f'test clusters with >={lo} distinct antibodies')
    sub = [r for r in used if depth.get(r['cluster'], 0) == 1]
    res['singly_sampled'] = _table(sub, [pred_by_id[r['id']] for r in sub],
                                   'test clusters sampled by exactly 1 antibody')

    # ---- union-epitope variant
    uidx = _index(union_labels)
    utest = [r for r in uidx if r['split'] == 'test' and r['id'] in pred_by_id]
    res['union_epitope'] = _table(utest, [pred_by_id[r['id']] for r in utest],
                                  'all test clusters, scored against the cluster-union epitope')
    per = {r['id']: r['n_label'] for r in utest}
    base = {r['id']: r['n_label'] for r in used}
    res['union_epitope']['label_growth'] = {
        'mean_n_epitope_per_instance': round(float(np.mean([base[i] for i in per])), 2),
        'mean_n_union_per_instance': round(float(np.mean(list(per.values()))), 2),
        'mean_ratio': round(float(np.mean([per[i] / max(1, base[i]) for i in per])), 3)}
    res['union_vs_perinstance_delta'] = {
        'majority_hit': {str(k): round(res['union_epitope']['majority_hit'][str(k)]
                                       - res['all_test']['majority_hit'][str(k)], 4) for k in KS},
        'best_f1': {str(k): round(res['union_epitope']['best_f1'][str(k)]
                                  - res['all_test']['best_f1'][str(k)], 4) for k in KS}}
    # union restricted to multiply-sampled clusters, where the union actually differs
    msub = [r for r in utest if depth.get(r['cluster'], 0) >= 3]
    res['union_epitope_ge3'] = _table(msub, [pred_by_id[r['id']] for r in msub],
                                      'union epitope, test clusters with >=3 distinct antibodies')

    # ---- headline excluding recurring antibodies
    for thr in (2, 3, 5):
        bad = {a for a, v in hspread.items() if len(v) >= thr}
        drop = {i for i in pred_by_id if ab.get(i) in bad}
        keep = [r for r in used if r['id'] not in drop]
        key = f'excl_antibodies_vs_ge{thr}_unrelated_antigens'
        res[key] = _table(keep, [pred_by_id[r['id']] for r in keep],
                          f'test, excluding antibodies seen against >={thr} unrelated antigens')
        res[key]['excluded'] = {
            'n_antibodies': len(bad),
            'n_instances_all_splits': sum(1 for i in ab if ab[i] in bad and i in inst_meta),
            'n_test_instances': len(drop),
            'n_test_clusters_lost': res['all_test']['n_clusters'] - res[key]['n_clusters']}
    jdump(OUT / 'metrics.json', res)
    print('wrote', OUT / 'metrics.json')


# ---------------------------------------------------------------- stage: report

def stage_report(_):
    comp = json.loads((OUT / 'sampling_completeness.json').read_text())
    met = json.loads((OUT / 'metrics.json').read_text())
    cl = comp['clusters']

    def strat(pred):
        sel = [c for c in cl if pred(cl[c])]
        if not sel:
            return None
        f = [cl[c]['dominant_group']['frac_exposed_labelled'] for c in sel
             if cl[c]['dominant_group']['frac_exposed_labelled'] is not None]
        return {'n_clusters': len(sel),
                'n_instances': sum(cl[c]['n_instances'] for c in sel),
                'median_frac_exposed_labelled': round(float(np.median(f)), 4),
                'mean_frac_exposed_labelled': round(float(np.mean(f)), 4),
                'p90_frac_exposed_labelled': round(float(np.percentile(f, 90)), 4),
                'mean_n_union_epitope_residues': round(
                    float(np.mean([cl[c]['n_union_epitope_residues'] for c in sel])), 1)}
    strata = {
        '1_antibody': strat(lambda d: d['n_distinct_antibodies'] == 1),
        '2to4_antibodies': strat(lambda d: 2 <= d['n_distinct_antibodies'] <= 4),
        '5plus_antibodies': strat(lambda d: d['n_distinct_antibodies'] >= 5),
        'all': strat(lambda d: True),
    }
    test_only = {k: strat(lambda d, k=k: 'test' in d['splits'] and (
        d['n_distinct_antibodies'] == 1 if k == '1_antibody' else
        2 <= d['n_distinct_antibodies'] <= 4 if k == '2to4_antibodies' else
        d['n_distinct_antibodies'] >= 5 if k == '5plus_antibodies' else True))
        for k in ('1_antibody', '2to4_antibodies', '5plus_antibodies', 'all')}
    # The stratified majority_hit values are not comparable to each other directly --
    # each stratum has its own candidate-pool difficulty, which the matched random
    # control absorbs. Lift over that control is the comparable quantity.
    lift = {}
    for key, b in met.items():
        if not isinstance(b, dict) or 'random_majority_hit' not in b:
            continue
        lift[key] = {'label': b['label'], 'n_interfaces': b['n_interfaces'],
                     'n_clusters': b['n_clusters'],
                     'majority_hit_minus_random': {
                         k: round(b['majority_hit'][k] - b['random_majority_hit'][k]['mean'], 4)
                         for k in map(str, KS)},
                     'majority_hit_sd_above_random': {
                         k: round((b['majority_hit'][k] - b['random_majority_hit'][k]['mean'])
                                  / max(b['random_majority_hit'][k]['sd'], 1e-9), 1)
                         for k in map(str, KS)},
                     'best_f1_minus_random': {
                         k: round(b['best_f1'][k] - b['random_best_f1'][k]['mean'], 4)
                         for k in map(str, KS)}}
    # Deeply-sampled antigens are also bigger and harder, which confounds any
    # comparison of raw majority_hit across sampling-depth strata. Size the confound.
    with (OUT / 'contexts.pkl').open('rb') as f:
        ctxs = pickle.load(f)
    rows = []
    inst_meta = {}
    for cidx, c in ctxs.items():
        n_exp = int((c['rsa'] >= RSA_EXPOSED).sum())
        for inst in c['instances']:
            inst_meta[inst['id']] = (c['pdb'], inst['split'], inst['cluster'])
            if inst['split'] == 'test':
                rows.append((cl[inst['cluster']]['n_distinct_antibodies'],
                             len(c['patches']), n_exp, len(c['display_keys'])))
    del ctxs
    # a single antibody over-represented in the benchmark is an exposure even when its
    # antigen is always the same one (a reference antibody re-crystallised many times)
    ab = json.loads((OUT / 'ab_clusters.json').read_text())['instance_to_antibody']
    hom = json.loads((OUT / 'antigen_homology.json').read_text())['cluster_to_component']
    byab = collections.defaultdict(list)
    for iid, a in ab.items():
        if iid in inst_meta:
            byab[a].append(iid)
    reused = []
    for a, ids in sorted(byab.items(), key=lambda kv: -len(kv[1]))[:15]:
        reused.append({'antibody': a, 'n_instances': len(ids),
                       'n_test_instances': sum(1 for i in ids if inst_meta[i][1] == 'test'),
                       'n_pdb_entries': len({inst_meta[i][0] for i in ids}),
                       'n_antigen_clusters': len({inst_meta[i][2] for i in ids}),
                       'n_unrelated_antigens': len({hom.get(inst_meta[i][2], inst_meta[i][2])
                                                    for i in ids}),
                       'pdb_ids': sorted({inst_meta[i][0] for i in ids})})
    diff = {}
    for name, lo, hi in (('1_antibody', 1, 1), ('2to4_antibodies', 2, 4),
                         ('5plus_antibodies', 5, 10 ** 6), ('all', 1, 10 ** 6)):
        s = [r for r in rows if lo <= r[0] <= hi]
        diff[name] = {'n_test_interfaces': len(s),
                      'mean_candidate_patches': round(float(np.mean([r[1] for r in s])), 1),
                      'mean_exposed_residues': round(float(np.mean([r[2] for r in s])), 1),
                      'mean_modelled_residues': round(float(np.mean([r[3] for r in s])), 1)}
    final = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
             'lift_over_matched_random_control': lift,
             'test_difficulty_by_sampling_depth': diff,
             'most_reused_antibodies': reused,
             'thresholds': {'rsa_exposed': RSA_EXPOSED, 'rsa_sensitivity': list(RSA_SENSITIVITY),
                            'antibody_identity_pct': AB_PIDENT, 'antibody_coverage': AB_COVER,
                            'antigen_chain_group_ratio': CHAIN_GROUP_RATIO,
                            'random_control_reps': RANDOM_REPS},
             'alignment': comp['alignment'],
             'sampling_depth_distribution': {
                 k: (v and {kk: v[kk] for kk in ('n_clusters', 'n_instances')}) for k, v in strata.items()},
             'completeness_by_stratum_all_clusters': strata,
             'completeness_by_stratum_test_clusters': test_only,
             'metrics': met}
    jdump(OUT / 'label_sampling_audit.json', final)
    print(json.dumps({'strata': strata, 'test_strata': test_only}, indent=2))
    print('wrote', OUT / 'label_sampling_audit.json')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['seqs', 'abclust', 'prep', 'align', 'antigenhom',
                                      'metrics', 'report'])
    a = ap.parse_args()
    {'seqs': stage_seqs, 'abclust': stage_abclust, 'prep': stage_prep,
     'align': stage_align, 'antigenhom': stage_antigenhom,
     'metrics': stage_metrics, 'report': stage_report}[a.stage](a)
