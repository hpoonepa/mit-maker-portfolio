"""Proper permutation null: shuffle labels WITHIN each instance (preserving the
per-instance positive count), refit, repeat. Gives a null distribution rather
than one draw."""
import gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.metrics import per_residue_auroc
import numpy as np
from scipy.optimize import minimize
NAMES=["exposure","concavity","hydrophobicity","connectivity"]

def load(p):
    X=[];y=[];g=[];inst=[]
    opener = gzip.open if str(p).endswith(".gz") else open
    with opener(p, "rt") as stream:
        for line in stream:
            d=json.loads(line)
            if "res" not in d: continue
            for r in d["res"]:
                X.append(r[1:5]); y.append(r[5]); g.append(d["cluster"]); inst.append(d["id"])
    return np.array(X,float), np.array(y,int), np.array(g), np.array(inst)

def fit(X,y,l2=1.0):
    Xb=np.hstack([X,np.ones((len(X),1))])
    def nll(w):
        z=np.clip(Xb@w,-500,500)
        return -np.sum(y*z-np.logaddexp(0,z))/len(y)+l2*np.sum(w[:-1]**2)/len(y)
    return minimize(nll,np.zeros(Xb.shape[1]),method="L-BFGS-B").x


def macro(s,y,g):
    v=[per_residue_auroc(s[g==c],y[g==c]) for c in np.unique(g)
       if 0 < y[g==c].sum() < (g==c).sum()]
    v=[x for x in v if x==x]
    return float(np.mean(v))

Xtr,ytr,gtr,itr = load(sys.argv[1])
Xte,yte,gte,ite = load(sys.argv[2])
Xteb=np.hstack([Xte,np.ones((len(Xte),1))])

real = macro(Xteb@fit(Xtr,ytr), yte, gte)
expo = macro(Xte[:,0], yte, gte)
cur  = macro(Xte@np.array([0.40,0.30,0.20,0.10]), yte, gte)

rng=np.random.default_rng(0)
nulls=[]
for t in range(12):
    ysh=ytr.copy()
    for i in np.unique(itr):              # shuffle WITHIN instance
        m=itr==i; v=ysh[m]; rng.shuffle(v); ysh[m]=v
    nulls.append(macro(Xteb@fit(Xtr,ysh), yte, gte))
nulls=np.array(nulls)

print(f"test: {len(yte)} residues, {yte.sum()} pos, {len(np.unique(gte))} clusters\n")
print(f"{'arm':30} {'macro AUROC':>12}")
print(f"{'current untuned weights':30} {cur:>12.4f}")
print(f"{'exposure only':30} {expo:>12.4f}")
print(f"{'fitted on train (4 features)':30} {real:>12.4f}")
print(f"\nwithin-instance permutation null over {len(nulls)} refits:")
print(f"   mean {nulls.mean():.4f}   sd {nulls.std():.4f}   range [{nulls.min():.4f}, {nulls.max():.4f}]")
print(f"   fitted model is {(real-nulls.mean())/max(nulls.std(),1e-9):.1f} sd above the null mean")
print(f"   null exceeds the fitted model in {int((nulls>=real).sum())}/{len(nulls)} refits")
