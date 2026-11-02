"""Exact significance test of a patch ranker against uniform patch selection.

Two mistakes this script has made and no longer makes, both recorded because the
numbers they produced were published.

**One sampled random draw per antigen.** The first version drew a single random
top-k set per antigen and ran McNemar against it. That spends almost all the
available power on the random arm's own coin-flip variance. The null here is
exact: for a pool of ``n`` patches of which ``h`` qualify, a uniform top-k draw
qualifies with probability ``1 - C(n-h, k)/C(n, k)``, and the count over antigens
is Poisson-binomial, computed by convolution.

**A shared pool.** The second version computed one null from the ``exposure``
arm's pool and compared every arm to it. Non-maximum suppression runs in score
order, so each arm keeps a *different* pool — in the committed artifact the sizes
differ on 187 of 199 antigens and the qualifying counts on 155. Each arm is now
tested against a uniform draw from its own pool. The correction is not cosmetic
and it does not uniformly flatter: ``fitted`` pools are smaller *and* hold fewer
hits, which lowered its null and its p-value (0.0071 to 0.0036 at k=5), while
``shipped``'s null fell too.

**The leak stratum.** ``cluster_id`` in the manifest is a ``+``-joined *set* of
accession tokens. Different cluster ids can share an antigen accession:
``up:P0DTC2`` (test) and ``up:M1E1E4+P0DTC2`` (train) are different clusters that
share SARS-CoV-2 spike. 25.0% of test instances share an accession with train or
val. Passing the manifest makes the test report a leak-free stratum alongside the
full one, so a reader can see whether the result depends on the leak. It does not.
"""
import gzip
import json
import sys
from math import comb

KS = (1, 3, 5, 10)
ARMS = ("fitted", "exposure", "shipped")


def _open(path):
    """Read the committed .gz artifact or a plain .jsonl interchangeably."""
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def cluster_tokens(cluster_id):
    """The accession/sequence tokens a cluster id is built from.

    Needed because the id is a joined set, not an atom: comparing whole ids finds
    no overlap between splits while a quarter of the antigens are shared.
    """
    body = cluster_id.split(":", 1)[1] if ":" in cluster_id else cluster_id
    return set(body.split("+"))


def train_val_tokens(manifest_path):
    import csv

    seen = set()
    with open(manifest_path) as fh:
        for row in csv.DictReader(fh):
            if row["split"] in ("train", "val"):
                seen |= cluster_tokens(row["cluster_id"])
    return seen


def p_hit(pool_n, hit_n, k):
    k = min(k, pool_n)
    miss = pool_n - hit_n
    return 1.0 if k > miss else 1.0 - comb(miss, k) / comb(pool_n, k)


def poisson_binomial(ps):
    """Exact pmf of a sum of independent Bernoulli(p_i), by convolution."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for j, d in enumerate(dist):
            nxt[j] += d * (1.0 - p)
            nxt[j + 1] += d * p
        dist = nxt
    return dist


def loose(size, inter):
    """A top-k patch shares at least one residue with the epitope.

    Near-saturated and reported only so its saturation is visible: the pool is
    already restricted to exposed surface, so chance alone reaches ~26% at k=1.
    """
    return inter >= 1


def strict(size, inter):
    """A majority of the patch's residues are epitope.

    Patch-side purity: the patch is *on* the site rather than beside it. Not the
    same criterion as ``benchmark.metrics.top_k_patch_recall``, which asks the
    epitope-side question and is bounded by the patch size cap.
    """
    return inter * 2 >= size


def report(recs, label, hit):
    print("=" * 78)
    print(f"{label}   n = {len(recs)} antigens, "
          f"{len({d['cluster'] for d in recs})} clusters")
    print("  null is a uniform draw from EACH ARM'S OWN post-NMS pool")
    print("=" * 78)
    print(f"  {'k':>3} {'arm':>9} {'observed':>9} {'E[random]':>10} {'sd':>6} "
          f"{'p (exact)':>11}  verdict")
    for k in KS:
        for arm in ARMS:
            ps = [
                p_hit(len(d[arm]), sum(1 for s, i in d[arm] if hit(s, i)), k)
                for d in recs
            ]
            obs = sum(1 for d in recs if any(hit(s, i) for s, i in d[arm][:k]))
            pval = sum(poisson_binomial(ps)[obs:])
            verdict = ("*** p<0.001" if pval < 1e-3 else
                       "**  p<0.01" if pval < 1e-2 else
                       "*   p<0.05" if pval < 0.05 else
                       "    ns")
            print(f"  {k:>3} {arm:>9} {obs:>9} {sum(ps):>10.1f} "
                  f"{sum(p * (1 - p) for p in ps) ** 0.5:>6.1f} "
                  f"{pval:>11.3g}  {verdict}")
        print()


def main(argv):
    if not 2 <= len(argv) <= 3:
        raise SystemExit(
            "usage: patch_pool_significance.py POOL.jsonl[.gz] [manifest.csv]\n"
            "  passing the manifest adds the leak-free stratum"
        )
    recs = [json.loads(line) for line in _open(argv[1])]
    recs = [d for d in recs if "err" not in d]

    strata = [("ALL TEST ANTIGENS", recs)]
    if len(argv) == 3:
        trval = train_val_tokens(argv[2])
        clean = [d for d in recs if not (cluster_tokens(d["cluster"]) & trval)]
        n_leak = len(recs) - len(clean)
        print(f"leak check: {n_leak}/{len(recs)} ({n_leak / len(recs):.1%}) of these "
              f"test antigens share an accession token with train or val.\n"
              f"Reporting both strata; the leak-free one is the defensible number.\n")
        strata.append(("LEAK-FREE STRATUM (no accession shared with train/val)", clean))

    for name, subset in strata:
        for crit, hit in (("STRICT: a top-k patch is majority epitope", strict),
                          ("LOOSE: a top-k patch touches the epitope", loose)):
            report(subset, f"{crit}\n{name}", hit)


if __name__ == "__main__":
    main(sys.argv)
