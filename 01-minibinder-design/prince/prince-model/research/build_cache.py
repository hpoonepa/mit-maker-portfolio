"""Build target-only features and exact original patch pools without changing PRINCE."""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, csv, gzip, hashlib, json, sys, time
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
from benchmark.geometric_predictor import GeometricArm
from hotspot_preflight.predict.geometric import GeometricPredictor
from hotspot_preflight.predict.features import residue_names, residue_points
from hotspot_preflight.surface import enumerate_patches
from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa

AA = ['ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE','LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL','UNK']
BASE = ['exposure','concavity','hydrophobicity','connectivity']
FEATURES = BASE + ['relative_sasa','log_target_residues'] + ['aa_'+x for x in AA] + ['charge','aromatic','polar']
for radius in (6,10,14):
    FEATURES += [f'r{radius}_{x}' for x in ['log_neighbors','surface_fraction','mean_exposure','hydrophobic_fraction','mean_charge','anisotropy','planarity']]

def keystr(k):
    return f'{k.auth_asym_id}:{k.auth_seq_id}' + (f':{k.icode}' if k.icode else '')

def build(task):
    context_id, instance, rows, out = task
    start = time.monotonic()
    path = Path(out)/f'{context_id}.json.gz'
    if path.exists():
        with gzip.open(path,'rt') as stream: saved=json.load(stream)
        if saved.get('feature_names') != FEATURES: raise ValueError('incompatible cached features')
        return {'context':context_id,'cached':True,'instances':len(rows)}
    target, assembly = load_antigen(ROOT/'.cache/benchmark/cif',instance.pdb_id,instance.antigen_chains)
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
    coord_path=locate_structure(ROOT/'.cache/benchmark/cif',instance.pdb_id)
    if len(set(str(k) for k in keys))!=len(keys):raise ValueError('ambiguous display residue identities')
    result={'cache_version':'all_declared_antigen_chains_v2','context_id':context_id,'pdb':instance.pdb_id,'chains':list(instance.antigen_chains),'assembly_used':assembly,'coordinate_sha256':hashlib.sha256(coord_path.read_bytes()).hexdigest(),'feature_names':FEATURES,'keys':[keystr(k) for k in keys],'display_keys':[str(k) for k in keys],'coordinates':[points[k] for k in keys],'features':feats,'patches':patch_rows,'instances':rows}
    with gzip.open(path,'wt') as stream:json.dump(result,stream,allow_nan=False)
    return {'context':context_id,'residues':len(keys),'patches':len(patches),'instances':len(rows),'seconds':round(time.monotonic()-start,2)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=3);ap.add_argument('--limit',type=int);args=ap.parse_args()
    out=DATA / 'cache_full_antigen';out.mkdir(parents=True, exist_ok=True)
    model=json.loads((ROOT/'data/eval/prince_connected.json').read_text())
    manifest=ROOT/'data/eval/prince_connected.manifest.csv'
    with manifest.open() as stream:rows=list(csv.DictReader(stream))
    by_id={r['instance_id']:r for r in rows};groups={}
    for split,ids in model['split_ids'].items():
        loaded,dropped=load_manifest(manifest,split=split)
        canonical={i.instance_id:i for i in loaded}
        for iid in ids:
            r=by_id[iid];cid=f"{r['pdb_id']}:{'+'.join(_antibody_chains(r))}";inst=canonical[cid]
            context=hashlib.sha256(json.dumps([inst.pdb_id,inst.antigen_chains]).encode()).hexdigest()[:16]
            if context not in groups:groups[context]=[inst,[]]
            groups[context][1].append({'id':iid,'canonical_id':cid,'split':split,'cluster':inst.cluster_id,'epitope':list(inst.epitope_residues)})
    tasks=[(k,i,r,str(out)) for k,(i,r) in sorted(groups.items())]
    if args.limit:tasks=tasks[:args.limit]
    results=[];errors=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        fs={pool.submit(build,t):t[0] for t in tasks}
        for n,f in enumerate(as_completed(fs),1):
            try:r=f.result();results.append(r);print(f'{n}/{len(tasks)} '+json.dumps(r),flush=True)
            except Exception as e:errors.append({'context':fs[f],'error':repr(e)});print('ERROR '+json.dumps(errors[-1]),flush=True)
    receipt={'contexts_requested':len(tasks),'completed':len(results),'instances_requested':sum(len(t[2]) for t in tasks),'errors':errors,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [manifest,ROOT/'data/eval/prince_connected.json',ROOT/'src/hotspot_preflight/surface.py',ROOT/'src/hotspot_preflight/predict/features.py']},'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'feature_names':FEATURES,'results':results}
    (DATA/('cache_full_antigen_smoke.json' if args.limit else 'cache_full_antigen_receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
