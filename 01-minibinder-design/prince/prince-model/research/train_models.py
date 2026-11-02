"""Validation-selected site models. The historical test is read only after locking."""
from __future__ import annotations
from paths import DATA, REPO, MODEL
import argparse, gzip, hashlib, json, pickle, sys, time
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(DATA / 'deps'))
from xgboost import XGBClassifier, XGBRegressor, XGBRanker

KS=(1,3,5,10)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):Path(path).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')

def load(original=False):
    receipt=json.loads((DATA/('cache_receipt.json' if original else 'cache_full_antigen_receipt.json')).read_text())
    if receipt['errors'] or receipt['instances_requested']!=589:raise ValueError('incomplete input cache')
    splits=defaultdict(list)
    for path in sorted((DATA/('cache' if original else 'cache_full_antigen')).glob('*.json.gz')):
        with gzip.open(path,'rt') as stream:d=json.load(stream)
        x=np.asarray(d['features'],dtype=np.float32)
        indices=[np.asarray(p['indices'],dtype=int) for p in d['patches']]
        if not indices:raise ValueError(f"No patches for {d['context_id']}; must explicitly score an empty proposal")
        xp=np.array([np.concatenate([x[ix].mean(0),x[ix].std(0),x[ix].max(0),[len(ix),p['area'],p['radius_gyration']]]) for ix,p in zip(indices,d['patches'])],dtype=np.float32)
        for inst in d['instances']:
            positive=set(inst['epitope'])
            y=np.array([k in positive for k in d['display_keys']],dtype=np.int32)
            if not original and y.sum()!=len(positive):raise ValueError(f"label identity lost: {inst['id']}: {sorted(positive-set(d['display_keys']))}")
            purity=np.array([y[ix].mean() for ix in indices])
            coverage=np.array([y[ix].sum()/len(positive) for ix in indices])
            splits[inst['split']].append({**inst,'context':d['context_id'],'x':x,'xp':xp,'y':y,'purity':purity,'coverage':coverage,'indices':indices,'areas':np.array([p['area'] for p in d['patches']]),'keys':d['keys'],'feature_names':d['feature_names']})
    for split,n in [('train',340),('val',139),('test',110)]:
        splits[split].sort(key=lambda r:r['id'])
        if len(splits[split])!=n:raise ValueError(f'wrong {split} denominator')
    for a,b in [('train','val'),('train','test'),('val','test')]:
        if {r['cluster'] for r in splits[a]}&{r['cluster'] for r in splits[b]}:raise ValueError('cluster leakage')
    return splits

def nms(row,scores):
    if len(scores)!=len(row['indices']) or not np.isfinite(scores).all():raise ValueError('invalid patch scores')
    # Cache patches already have area/canonical order, matching original tie break.
    order=np.argsort(-scores,kind='stable');selected=[];sets=[set(ix.tolist()) for ix in row['indices']]
    for idx in order:
        if all(len(sets[idx]&sets[j])/len(sets[idx]|sets[j])<.5 for j in selected):selected.append(int(idx))
        if len(selected)>=10:break
    return selected

def metrics(rows,predictions):
    outcomes=[]
    for r,s in zip(rows,predictions):
        order=nms(r,np.asarray(s))
        out={'id':r['id'],'cluster':r['cluster'],'n_candidates':len(s),'order':order}
        for metric,label in [('majority_hit',r['purity']>.5),('half_epitope_recovery',r['coverage']>=.5)]:
            out[metric]={str(k):bool(np.any(label[order[:k]])) for k in KS}
        out['oracle_majority']=bool(np.any(r['purity']>.5));out['oracle_half_epitope']=bool(np.any(r['coverage']>=.5))
        outcomes.append(out)
    summary={}
    for metric in ['majority_hit','half_epitope_recovery']:
        summary[metric]={}
        for k in KS:
            groups=defaultdict(list)
            for o in outcomes:groups[o['cluster']].append(o[metric][str(k)])
            summary[metric][str(k)]={'hits':sum(o[metric][str(k)] for o in outcomes),'n':len(rows),'component_macro':float(np.mean([np.mean(v) for v in groups.values()]))}
    summary['oracle']={'majority_hits':sum(o['oracle_majority'] for o in outcomes),'half_epitope_hits':sum(o['oracle_half_epitope'] for o in outcomes),'n':len(rows)}
    return {'summary':summary,'outcomes':outcomes}

def baseline(rows,weights):return [np.array([(r['x'][ix,:4]@weights).mean() for ix in r['indices']]) for r in rows]
def predictions(model,rows,kind,features):
    out=[]
    for r in rows:
        x=r['x'][:,:4] if features=='four' else r['x']
        x=x if kind=='residue' else r['xp']
        s=model.predict_proba(x)[:,1] if kind in ('residue','patch_classifier') else model.predict(x)
        out.append(np.array([s[ix].mean() for ix in r['indices']]) if kind=='residue' else s)
    return out

def train(rows,config):
    kind,features,depth=config['kind'],config['features'],config['depth']
    groups=Counter(r['cluster'] for r in rows)
    x=[];y=[];weights=[];sizes=[];group_weights=[]
    for r in rows:
        if kind=='residue':
            xx=r['x'][:,:4] if features=='four' else r['x'];yy=r['y']
        else:
            xx=r['xp'];yy=(r['purity']>.5).astype(int) if kind=='patch_classifier' else r['purity']
            if kind=='patch_ranker':yy=np.floor(yy*4).astype(int)
        x.append(xx);y.append(yy);sizes.append(len(yy));weights.extend([1/(groups[r['cluster']]*len(yy))]*len(yy));group_weights.append(1/groups[r['cluster']])
    x=np.concatenate(x);y=np.concatenate(y);weights=np.asarray(weights);weights*=len(weights)/weights.sum()
    kwargs=dict(n_estimators=200,max_depth=depth,learning_rate=.05,subsample=.8,colsample_bytree=.8,min_child_weight=10,reg_lambda=10,random_state=17,n_jobs=3,tree_method='hist')
    if kind in ('residue','patch_classifier'):
        model=XGBClassifier(**kwargs,objective='binary:logistic',eval_metric='logloss');model.fit(x,y,sample_weight=weights)
    elif kind=='patch_regressor':
        model=XGBRegressor(**kwargs,objective='reg:squarederror');model.fit(x,y,sample_weight=weights)
    else:
        model=XGBRanker(**kwargs,objective='rank:ndcg',lambdarank_pair_method='topk',lambdarank_num_pair_per_sample=10);model.fit(x,y,group=sizes,sample_weight=np.array(group_weights))
    return model

def paired(left,right):
    out={};rng=np.random.default_rng(17)
    assert [r['id'] for r in left['outcomes']]==[r['id'] for r in right['outcomes']]
    for metric in ['majority_hit','half_epitope_recovery']:
        out[metric]={}
        for k in KS:
            groups=defaultdict(list)
            for a,b in zip(left['outcomes'],right['outcomes']):groups[a['cluster']].append(int(a[metric][str(k)])-int(b[metric][str(k)]))
            values=np.array([np.mean(groups[c]) for c in sorted(groups)])
            boot=values[rng.integers(len(values),size=(5000,len(values)))].mean(axis=1)
            out[metric][str(k)]={'component_difference':float(values.mean()),'ci95':np.quantile(boot,[.025,.975]).tolist()}
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['select','test'],required=True);args=ap.parse_args()
    rows=load();old=json.loads((REPO/'data/eval/prince_connected.json').read_text());w=np.array([old['weights'][f] for f in ['exposure','concavity','hydrophobicity','connectivity']])
    models=DATA / 'models';models.mkdir(parents=True, exist_ok=True)
    if args.phase=='select':
        configs=[]
        for features in ['four','enriched']:
            for depth in [2,4]:configs.append({'kind':'residue','features':features,'depth':depth})
        for kind in ['patch_classifier','patch_regressor','patch_ranker']:
            for depth in ([3,5] if kind=='patch_ranker' else [2,4]):configs.append({'kind':kind,'features':'enriched','depth':depth})
        results={'incumbent':metrics(rows['val'],baseline(rows['val'],w)),'exposure':metrics(rows['val'],baseline(rows['val'],np.array([1,0,0,0])))}
        for config in configs:
            name=f"{config['kind']}_{config['features']}_d{config['depth']}";start=time.monotonic()
            model=train(rows['train'],config);model.save_model(models/f'{name}.json')
            result=metrics(rows['val'],predictions(model,rows['val'],config['kind'],config['features']));result['config']=config;result['seconds']=time.monotonic()-start;results[name]=result
            write(DATA / 'validation_results.json',results)
            print(name,json.dumps(result['summary']),flush=True)
        def selection(name):return tuple(results[name]['summary']['majority_hit'][str(k)]['component_macro'] for k in [1,3,10])
        winner=max(results,key=selection)
        lock={'winner':winner,'config':results[winner].get('config'),'selection':'validation component-macro majority top1 then top3 then top10','test_used_for_selection':False,'validation_sha256':digest(DATA / 'validation_results.json'),'script_sha256':digest(__file__),'protocol_sha256':digest(DATA / 'PROTOCOL.md'),'model_sha256':digest(models/f'{winner}.json') if winner not in ['incumbent','exposure'] else None,'validation_summary':results[winner]['summary']}
        write(DATA / 'selection_lock.json',lock);print('LOCKED',json.dumps(lock),flush=True)
    else:
        lock=json.loads((DATA / 'selection_lock.json').read_text())
        if lock['validation_sha256']!=digest(DATA / 'validation_results.json'):raise ValueError('selection history changed')
        config=lock['config'];winner=lock['winner']
        if config:
            cls=XGBClassifier if config['kind'] in ['residue','patch_classifier'] else XGBRegressor if config['kind']=='patch_regressor' else XGBRanker
            model=cls();model.load_model(models/f'{winner}.json');pred=predictions(model,rows['test'],config['kind'],config['features'])
        else:pred=baseline(rows['test'],w if winner=='incumbent' else np.array([1,0,0,0]))
        original=load(original=True)
        result={'status':'retrospective_test_after_validation_selection','selection':lock,'original_incumbent':metrics(original['test'],baseline(original['test'],w)),'original_exposure':metrics(original['test'],baseline(original['test'],np.array([1,0,0,0]))),'incumbent':metrics(rows['test'],baseline(rows['test'],w)),'exposure':metrics(rows['test'],baseline(rows['test'],np.array([1,0,0,0]))),'selected':metrics(rows['test'],pred)}
        result['paired_selected_minus_incumbent']=paired(result['selected'],result['incumbent'])
        frozen=json.loads((REPO/'data/eval/prince_connected_sites.json').read_text())
        mismatch=[]
        for name,oldname in [('original_incumbent','fitted'),('original_exposure','exposure_only')]:
            expected={r['id']:r for r in frozen['instances']}
            alias={r['id']:r['canonical_id'] for r in rows['test']}
            for o in result[name]['outcomes']:
                for metric in ['majority_hit','half_epitope_recovery']:
                    if o[metric]!=expected[alias[o['id']]]['arms'][oldname][metric]:mismatch.append([name,o['id'],metric])
        result['frozen_baseline_outcome_mismatches']=mismatch
        write(DATA / 'test_results.json',result)
        print(json.dumps({k:(v['summary'] if isinstance(v,dict) and 'summary' in v else v) for k,v in result.items()},indent=2))
        if mismatch:raise SystemExit('Baseline outcomes differ: inspect before claiming a comparable result')

if __name__=='__main__':main()
