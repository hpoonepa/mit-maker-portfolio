"""Where does the patch ranker actually lose?

Four quantities per antigen, all drawn from the SAME post-NMS candidate pool:

  oracle   - does ANY patch in the pool touch the epitope? The ceiling. If this
             is low, enumeration is missing the epitope and no ranking can help.
  random   - the pool's base rate, i.e. what a uniform draw achieves. Computed
             in closed form (hypergeometric, without replacement) rather than
             sampled, so there is no Monte-Carlo noise to argue with.
  ranked   - the arm's own top-k.
  strict   - same but a 'hit' requires the patch be majority epitope, which is
             what a binder designer actually needs.

Macro-averaged by antigen cluster, because the benchmark is cluster-imbalanced
and a per-instance mean would be dominated by whichever antigen has the most
deposited antibodies.
"""
import json, sys
from collections import defaultdict
from math import comb

PATH = sys.argv[1]
KS = (1, 3, 5, 10)
ARMS = ("exposure", "fitted", "shipped")

def _open(path):
    """Read the committed .gz artifact or a plain .jsonl interchangeably."""
    import gzip
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)



def random_hit_prob(pool_n, hit_n, k):
    """P(at least one hit in k draws without replacement) from a pool of pool_n."""
    k = min(k, pool_n)
    miss = pool_n - hit_n
    if k > miss:
        return 1.0
    return 1.0 - comb(miss, k) / comb(pool_n, k)


recs, errs = [], 0
for line in _open(PATH):
    d = json.loads(line)
    if "err" in d:
        errs += 1
        continue
    recs.append(d)

print(f"{len(recs)} antigens, {errs} errored\n")

# per-antigen outcomes, then macro-average by cluster
def hit_loose(size, inter):
    return inter >= 1

def hit_strict(size, inter):
    return inter * 2 >= size      # majority of the patch is epitope

for label, hit in (("LOOSE  (patch touches epitope, >=1 residue)", hit_loose),
                   ("STRICT (majority of patch IS epitope)", hit_strict)):
    by_cluster = defaultdict(lambda: defaultdict(list))
    for d in recs:
        c = d["cluster"]
        # Per arm, not shared. NMS runs in score order, so each arm keeps a
        # different pool — sizes differ on 187 of 199 antigens here. Scoring an
        # arm's top-k against another arm's pool compares it to the wrong null.
        for arm in ARMS:
            rows = d[arm]
            n = len(rows)
            nhit = sum(1 for s, i in rows if hit(s, i))
            by_cluster[c][f"oracle:{arm}"].append(1.0 if nhit else 0.0)
            for k in KS:
                by_cluster[c][f"random:{arm}@{k}"].append(
                    random_hit_prob(n, nhit, k)
                )
                by_cluster[c][f"{arm}@{k}"].append(
                    1.0 if any(hit(s, i) for s, i in rows[:k]) else 0.0
                )

    def macro(key):
        per = [sum(v[key]) / len(v[key]) for v in by_cluster.values() if key in v]
        return sum(per) / len(per)

    print("=" * 72)
    print(label)
    print(f"  {len(by_cluster)} clusters, macro-averaged; each arm against ITS OWN pool")
    print("=" * 72)
    print("  ORACLE (the arm's pool holds such a patch at all): "
          + ", ".join(f"{a} {macro(f'oracle:{a}'):.1%}" for a in ARMS))
    print()
    print(f"  {'k':>3} " + " ".join(
        f"{a:>9} {'(rand)':>8}" for a in ARMS))
    for k in KS:
        cells = " ".join(
            f"{macro(f'{a}@{k}'):>8.1%} {macro(f'random:{a}@{k}'):>8.1%}"
            for a in ARMS
        )
        print(f"  {k:>3} {cells}")
    print()

# pool shape
import statistics as st
pools = [len(d["exposure"]) for d in recs]
eps = [d["n_epitope"] for d in recs]
sizes = [s for d in recs for s, i in d["exposure"]]
print("=" * 66)
print("POOL SHAPE")
print("=" * 66)
print(f"  patches per antigen (post-NMS): median {st.median(pools):.0f}  "
      f"range {min(pools)}-{max(pools)}")
print(f"  enumerated before NMS:          median "
      f"{st.median([d['n_enumerated'] for d in recs]):.0f}")
print(f"  patch size (residues):          median {st.median(sizes):.0f}")
print(f"  epitope size (residues):        median {st.median(eps):.0f}")
