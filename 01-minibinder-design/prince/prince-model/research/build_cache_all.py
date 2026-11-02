"""Full-manifest twin of build_cache.py: identical feature semantics, every interface.

build_cache.py iterates prince_connected.json's 589-interface split_ids. This
iterates the whole prince_connected.manifest.csv (6937 rows / 1549 clusters)
using the manifest's own `split` column. Nothing about the 51 features, their
order, the patch pool, or the cache schema changes -- only WHICH interfaces are
processed. Output goes to cache_all/ so cache_full_antigen/ is never touched.
"""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, csv, gzip, hashlib, json, statistics, sys, time, urllib.error, urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
ROOT = REPO
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
from benchmark.evaluate import load_manifest, _antibody_chains
from benchmark.structures import load_antigen, locate_structure
from benchmark.geometric_predictor import GeometricArm  # noqa: F401  (parity with build_cache.py)
from hotspot_preflight.predict.geometric import GeometricPredictor
from hotspot_preflight.predict.features import residue_names, residue_points
from hotspot_preflight.surface import enumerate_patches
from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa

AA = ['ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE','LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL','UNK']
BASE = ['exposure','concavity','hydrophobicity','connectivity']
FEATURES = BASE + ['relative_sasa','log_target_residues'] + ['aa_'+x for x in AA] + ['charge','aromatic','polar']
for radius in (6,10,14):
    FEATURES += [f'r{radius}_{x}' for x in ['log_neighbors','surface_fraction','mean_exposure','hydrophobic_fraction','mean_charge','anisotropy','planarity']]

CIF_DIR = ROOT/'.cache/benchmark/cif'
SPLITS = ('train','val','test')
UA = 'hotspot-preflight-benchmark/1.0 (lambertigem621@gmail.com)'


class LabelIdentityError(ValueError):
    """An epitope residue is absent from the context's display_keys.

    Never swallowed and never softened: a missing label silently becomes a
    negative, which deflates every recall number computed downstream.
    """


def keystr(k):
    return f'{k.auth_asym_id}:{k.auth_seq_id}' + (f':{k.icode}' if k.icode else '')


def build(task):
    context_id, instance, rows, out = task
    start = time.monotonic()
    path = Path(out)/f'{context_id}.json.gz'
    if path.exists():
        try:
            with gzip.open(path,'rt') as stream: saved=json.load(stream)
        except Exception as exc:
            raise ValueError(f'unparseable cache {path.name}: {exc!r}')
        if saved.get('feature_names') != FEATURES: raise ValueError('incompatible cached features')
        return {'context':context_id,'cached':True,'instances':len(rows)}
    target, assembly = load_antigen(CIF_DIR,instance.pdb_id,instance.antigen_chains)
    profile = compute_burial(target.st,context='chain',focus_chain=None,reference=reference_max_sasa(target.st))
    original = set(instance.antigen_chains)
    candidate = replace(profile,relative_sasa={k:v for k,v in profile.relative_sasa.items() if k.auth_asym_id in original},absolute_sasa={k:v for k,v in profile.absolute_sasa.items() if k.auth_asym_id in original})
    patches = enumerate_patches(target,candidate,max_patches=None)
    components = GeometricPredictor(weights={x:1. for x in BASE}).score_components(target,profile)
    names, points = residue_names(target.st), residue_points(target.st)
    all_keys = sorted(set(points)&set(profile.relative_sasa))
    xyz = np.array([points[k] for k in all_keys])
    tree = cKDTree(xyz)
    all_index = {k:i for i,k in enumerate(all_keys)}
    exposure = np.array([profile.relative_sasa[k] for k in all_keys])
    hydro = np.array([names[k] in {'ALA','VAL','LEU','ILE','PRO','PHE','MET','TRP','CYS','TYR'} for k in all_keys])
    charge = np.array([1. if names[k] in {'ARG','LYS'} else -1. if names[k] in {'ASP','GLU'} else 0. for k in all_keys])
    keys = [k for k in all_keys if k.auth_asym_id in original]
    index = {k:i for i,k in enumerate(keys)}
    feats = []
    for k in keys:
        i=all_index[k]; name=names[k] if names[k] in AA else 'UNK'
        f=[components[k][x] for x in BASE]+[float(exposure[i]),float(np.log1p(len(keys)))]+[float(name==aa) for aa in AA]+[float(charge[i]),float(name in {'PHE','TYR','TRP'}),float(name in {'SER','THR','ASN','GLN'})]
        for radius in (6,10,14):
            ns=[j for j in tree.query_ball_point(xyz[i],radius) if j!=i]
            if ns:
                cloud=xyz[ns]-xyz[i]
                eig=np.linalg.eigvalsh(cloud.T@cloud/max(1,len(ns)))
                f += [float(np.log1p(len(ns))),float(np.mean(exposure[ns]>=.2)),float(np.mean(np.minimum(exposure[ns],1))),float(np.mean(hydro[ns])),float(np.mean(charge[ns])),float((eig[2]-eig[0])/max(eig[2],1e-9)),float((eig[1]-eig[0])/max(eig[2],1e-9))]
            else: f += [0.]*7
        feats.append(f)
    matrix=np.asarray(feats)
    if matrix.shape!=(len(keys),len(FEATURES)) or not np.isfinite(matrix).all():raise ValueError('invalid features')
    patch_rows=[]
    for p in patches:
        inds=[index[k] for k in p.residues]
        cloud=np.array([points[k] for k in p.residues]);center=cloud.mean(axis=0)
        patch_rows.append({'indices':inds,'area':p.area,'radius_gyration':float(np.sqrt(np.mean(np.sum((cloud-center)**2,axis=1))))})
    coord_path=locate_structure(CIF_DIR,instance.pdb_id)
    display=[str(k) for k in keys]
    if len(set(display))!=len(display):raise ValueError('ambiguous display residue identities')
    shown=set(display)
    failures=[{'id':r['id'],'canonical_id':r['canonical_id'],'split':r['split'],'missing':sorted(set(r['epitope'])-shown),'n_epitope':len(r['epitope'])} for r in rows if set(r['epitope'])-shown]
    if failures:
        raise LabelIdentityError(f'{len(failures)} instance(s) with epitope residues absent from display_keys in context {context_id}',failures)
    result={'cache_version':'all_declared_antigen_chains_v2','context_id':context_id,'pdb':instance.pdb_id,'chains':list(instance.antigen_chains),'assembly_used':assembly,'coordinate_sha256':hashlib.sha256(coord_path.read_bytes()).hexdigest(),'feature_names':FEATURES,'keys':[keystr(k) for k in keys],'display_keys':display,'coordinates':[points[k] for k in keys],'features':feats,'patches':patch_rows,'instances':rows}
    with gzip.open(path,'wt') as stream:json.dump(result,stream,allow_nan=False)
    return {'context':context_id,'residues':len(keys),'patches':len(patches),'instances':len(rows),'seconds':round(time.monotonic()-start,2)}


def fetch(pdb_id, attempts=4):
    """Politely pull one mmCIF from RCSB into the shared structure cache."""
    url=f'https://files.rcsb.org/download/{pdb_id.lower()}.cif.gz'
    target=CIF_DIR/f'{pdb_id.lower()}.cif.gz'
    for attempt in range(attempts):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':UA})
            with urllib.request.urlopen(request,timeout=120) as response: payload=response.read()
            if not payload: raise ValueError('empty body')
            target.write_bytes(payload)
            return True,len(payload)
        except urllib.error.HTTPError as exc:
            if exc.code in (429,500,502,503,504) and attempt+1<attempts:
                time.sleep(2**attempt);continue
            return False,f'HTTP {exc.code}'
        except Exception as exc:
            if attempt+1<attempts: time.sleep(2**attempt);continue
            return False,repr(exc)
    return False,'exhausted retries'


def collect():
    """(groups, dropped_report, cluster_splits, raw_rows_per_split) over the full manifest."""
    manifest=ROOT/'data/eval/prince_connected.manifest.csv'
    with manifest.open(newline='') as stream: rows=list(csv.DictReader(stream))
    raw_by_canonical={}
    for r in rows:
        canonical=f"{r['pdb_id'].strip()}:{'+'.join(_antibody_chains(r))}"
        raw_by_canonical.setdefault((r['split'].strip(),canonical),r['instance_id'])
    groups={};dropped_report={};loaded_counts={};cluster_splits=defaultdict(set)
    for split in SPLITS:
        loaded,dropped=load_manifest(manifest,split=split)
        loaded_counts[split]=len(loaded)
        dropped_report[split]={'count':len(dropped),'reasons':dict(Counter(getattr(d,'reason',str(d)) for d in dropped)),'examples':[{'stage':getattr(d,'stage',None),'id':getattr(d,'identifier',None),'reason':getattr(d,'reason',None)} for d in dropped[:25]]}
        for inst in loaded:
            cluster_splits[inst.cluster_id].add(split)
            context=hashlib.sha256(json.dumps([inst.pdb_id,inst.antigen_chains]).encode()).hexdigest()[:16]
            if context not in groups: groups[context]=[inst,[]]
            groups[context][1].append({'id':raw_by_canonical.get((split,inst.instance_id),inst.instance_id),'canonical_id':inst.instance_id,'split':split,'cluster':inst.cluster_id,'epitope':list(inst.epitope_residues)})
    return groups,dropped_report,loaded_counts,dict(cluster_splits),manifest


def oracle(out:Path):
    """Enumerated-patch ceilings on the test split: the headroom at this scale."""
    per_instance=[];patch_sizes=[];epitope_sizes=[]
    for path in sorted(out.glob('*.json.gz')):
        with gzip.open(path,'rt') as stream: d=json.load(stream)
        test=[i for i in d['instances'] if i['split']=='test']
        if not test: continue
        display=d['display_keys']
        sets=[frozenset(display[j] for j in p['indices']) for p in d['patches']]
        patch_sizes += [len(s) for s in sets]
        for inst in test:
            ep=set(inst['epitope']);epitope_sizes.append(len(ep))
            majority=any(len(s&ep)*2>len(s) for s in sets if s)
            covered=any(len(s&ep)*2>=len(ep) for s in sets) if ep else False
            per_instance.append({'id':inst['id'],'cluster':inst['cluster'],'majority':majority,'covered':covered,'n_patches':len(sets)})
    by_cluster=defaultdict(list)
    for r in per_instance: by_cluster[r['cluster']].append(r)
    def macro(field):
        return float(np.mean([np.mean([r[field] for r in v]) for v in by_cluster.values()])) if by_cluster else float('nan')
    return {'test_instances':len(per_instance),'test_clusters':len(by_cluster),
            'majority_correct_instances':sum(r['majority'] for r in per_instance),
            'majority_correct_instance_fraction':float(np.mean([r['majority'] for r in per_instance])) if per_instance else float('nan'),
            'majority_correct_cluster_macro':macro('majority'),
            'coverage_50_instances':sum(r['covered'] for r in per_instance),
            'coverage_50_instance_fraction':float(np.mean([r['covered'] for r in per_instance])) if per_instance else float('nan'),
            'coverage_50_cluster_macro':macro('covered'),
            'median_patch_size':statistics.median(patch_sizes) if patch_sizes else None,
            'median_epitope_size':statistics.median(epitope_sizes) if epitope_sizes else None,
            'median_patches_per_context':statistics.median([r['n_patches'] for r in per_instance]) if per_instance else None}


def audit(out:Path):
    """Cluster/split and instance tallies read back off disk, not off intent."""
    cluster_splits=defaultdict(set);per_split=Counter();contexts=0;clusters_per_split=defaultdict(set)
    for path in sorted(out.glob('*.json.gz')):
        with gzip.open(path,'rt') as stream: d=json.load(stream)
        contexts+=1
        for inst in d['instances']:
            per_split[inst['split']]+=1;cluster_splits[inst['cluster']].add(inst['split']);clusters_per_split[inst['split']].add(inst['cluster'])
    violations=[{'cluster':c,'splits':sorted(s)} for c,s in cluster_splits.items() if len(s)>1]
    return {'contexts_on_disk':contexts,'instances_per_split':dict(per_split),'clusters_total':len(cluster_splits),
            'clusters_per_split':{k:len(v) for k,v in clusters_per_split.items()},
            'cluster_disjointness_violations':violations}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--workers',type=int,default=3)
    ap.add_argument('--limit',type=int)
    ap.add_argument('--oracle',action='store_true',help='audit + oracle ceilings over an existing cache_all/, build nothing')
    args=ap.parse_args()
    out=DATA / 'cache_all';out.mkdir(parents=True, exist_ok=True)
    if args.oracle:
        report={'audit':audit(out),'oracle_test':oracle(out)}
        (DATA / 'cache_all_oracle.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2));return

    groups,dropped_report,loaded_counts,cluster_splits,manifest=collect()
    manifest_violations=[{'cluster':c,'splits':sorted(s)} for c,s in cluster_splits.items() if len(s)>1]
    print(f'manifest: loaded {loaded_counts} dropped '+json.dumps({k:v["count"] for k,v in dropped_report.items()}),flush=True)
    print(f'contexts {len(groups)} clusters {len(cluster_splits)} manifest_cluster_violations {len(manifest_violations)}',flush=True)

    needed=sorted({i.pdb_id for i,_ in groups.values()})
    missing=[p for p in needed if locate_structure(CIF_DIR,p) is None]
    fetched=[];unavailable=[]
    print(f'structures needed {len(needed)} missing {len(missing)}',flush=True)
    for n,pdb in enumerate(missing,1):
        ok,detail=fetch(pdb)
        (fetched if ok else unavailable).append({'pdb':pdb,'detail':detail})
        print(f'fetch {n}/{len(missing)} {pdb} {"ok" if ok else "FAILED"} {detail}',flush=True)
        time.sleep(0.5)

    tasks=[(k,i,r,str(out)) for k,(i,r) in sorted(groups.items())]
    if args.limit: tasks=tasks[:args.limit]
    results=[];errors=[];label_failures=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        fs={pool.submit(build,t):t[0] for t in tasks}
        for n,f in enumerate(as_completed(fs),1):
            try:
                r=f.result();results.append(r)
                if n%50==0 or n<=20 or args.limit: print(f'{n}/{len(tasks)} '+json.dumps(r),flush=True)
            except LabelIdentityError as e:
                label_failures += e.args[1] if len(e.args)>1 else []
                errors.append({'context':fs[f],'error':str(e.args[0]),'kind':'label_identity'})
                print('LABEL_IDENTITY '+json.dumps(errors[-1]),flush=True)
            except Exception as e:
                errors.append({'context':fs[f],'error':repr(e)})
                print('ERROR '+json.dumps(errors[-1]),flush=True)

    receipt={'contexts_requested':len(tasks),'completed':len(results),
             'instances_requested':sum(len(t[2]) for t in tasks),'errors':errors,
             'manifest_loaded_per_split':loaded_counts,'manifest_dropped':dropped_report,
             'manifest_cluster_violations':manifest_violations,
             'label_identity_failures':label_failures,
             'structures_fetched':fetched,'structures_unavailable':unavailable,
             'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [manifest,ROOT/'src/hotspot_preflight/surface.py',ROOT/'src/hotspot_preflight/predict/features.py']},
             'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'feature_names':FEATURES,'results':results}
    if not args.limit: receipt['audit']=audit(out)
    (DATA/('cache_all_smoke.json' if args.limit else 'cache_all_receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print('receipt written; completed '+str(len(results))+'/'+str(len(tasks))+' errors '+str(len(errors)),flush=True)
    if errors: raise SystemExit(1)


if __name__=='__main__':main()
