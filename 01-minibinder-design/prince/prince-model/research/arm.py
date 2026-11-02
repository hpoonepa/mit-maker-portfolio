"""Define the SAbDab2-based sensitivity arm for PRINCE's held-out read.

Two leakage questions, both answered against SAbDab2 v0.2.0 clusters:
  (A) ab-ag cluster leak: does one of our TEST instances share a SAbDab2
      ab_ag_cluster (CDRH3 95% / CDRH123 100% / CDRL123 100% / protein-antigen
      40% / peptide-DNA-RNA 80%, connected-component joined) with one of our
      TRAIN instances?
  (B) antigen-only leak: does one of our TEST antigen chains share a SAbDab2
      antigen cluster (the `agclusters` column) with one of our TRAIN antigen
      chains? This is the one that matters for an epitope/site ranker.

Usage: python -I arm.py <abag_split.csv> <prince_manifest.csv>
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import collections
import csv
import sys

csv.field_size_limit(1 << 30)
OUT_DIR = str(DATA / "sabdab2")


def norm_pdb(v: str) -> str:
    v = v.strip().lower()
    return v[4:].lstrip("0") if v.startswith("pdb_") and len(v) > 4 else v


def main() -> None:
    abag_path, manifest_path = sys.argv[1], sys.argv[2]

    theirs = {}
    for row in csv.DictReader(open(abag_path, newline="")):
        key = (norm_pdb(row["PDB_ID"]), (row["Hchain"] or "").strip(), (row["Lchain"] or "").strip())
        theirs[key] = {
            "abag_cluster": (row["ab_ag_cluster"] or "").strip(),
            "abag_split": (row["ab_ag_split"] or "").strip(),
            "agchains": (row["agchains"] or "").strip(),
            "agclusters": (row["agclusters"] or "").strip(),
            "agtypes": (row["agtypes"] or "").strip(),
        }

    ours = list(csv.DictReader(open(manifest_path, newline="")))
    rec_of = {}
    for r in ours:
        k = (norm_pdb(r["pdb_id"]), r["heavy_chain"].strip(), r["light_chain"].strip())
        if k in theirs:
            rec_of[r["instance_id"]] = theirs[k]

    def ag_clusters_for(r: dict) -> set[str]:
        """SAbDab2 antigen clusters for the antigen chains OUR manifest scores."""
        rec = rec_of.get(r["instance_id"])
        if not rec or not rec["agclusters"]:
            return set()
        chains = rec["agchains"].split("/")
        clusts = rec["agclusters"].split("/")
        types = rec["agtypes"].split("/")
        want = {c.strip() for c in r["antigen_chains"].split("|") if c.strip()}
        out = set()
        for ch, cl, ty in zip(chains, clusts, types):
            if ch in want and cl and cl.upper() not in ("", "NONE", "NAN"):
                out.add(f"{ty}:{cl}")
        return out

    # ---------------- (A) ab-ag cluster leak -------------------------------
    train_abag = {rec_of[r["instance_id"]]["abag_cluster"]
                  for r in ours if r["split"] == "train" and r["instance_id"] in rec_of}
    train_abag.discard("")

    test_rows = [r for r in ours if r["split"] == "test"]
    a_unmatched = [r for r in test_rows if r["instance_id"] not in rec_of]
    a_leaky = [r for r in test_rows if r["instance_id"] in rec_of
               and rec_of[r["instance_id"]]["abag_cluster"] in train_abag]
    a_clean = [r for r in test_rows if r["instance_id"] in rec_of
               and rec_of[r["instance_id"]]["abag_cluster"] not in train_abag]

    print("=== (A) ab-ag CLUSTER LEAK in OUR test split ===")
    print(f"our test instances                       : {len(test_rows)} ({len({r['cluster_id'] for r in test_rows})} our-clusters)")
    print(f"  not in SAbDab2 v0.2.0 (unassessable)   : {len(a_unmatched)} ({len({r['cluster_id'] for r in a_unmatched})} our-clusters)")
    print(f"  LEAKY: shares ab-ag cluster w/ our train: {len(a_leaky)} ({len({r['cluster_id'] for r in a_leaky})} our-clusters)")
    print(f"  CLEAN: no ab-ag cluster tie to our train: {len(a_clean)} ({len({r['cluster_id'] for r in a_clean})} our-clusters)")

    # ---------------- (B) antigen-only leak -------------------------------
    train_ag = set()
    for r in ours:
        if r["split"] == "train":
            train_ag |= ag_clusters_for(r)

    b_unmatched, b_noag, b_leaky, b_clean = [], [], [], []
    for r in test_rows:
        if r["instance_id"] not in rec_of:
            b_unmatched.append(r)
            continue
        cl = ag_clusters_for(r)
        if not cl:
            b_noag.append(r)
        elif cl & train_ag:
            b_leaky.append(r)
        else:
            b_clean.append(r)

    print("\n=== (B) ANTIGEN-ONLY CLUSTER LEAK in OUR test split (the one that matters for a site ranker) ===")
    print(f"  not in SAbDab2 v0.2.0                  : {len(b_unmatched)} ({len({r['cluster_id'] for r in b_unmatched})} our-clusters)")
    print(f"  matched but antigen chain not retained : {len(b_noag)} ({len({r['cluster_id'] for r in b_noag})} our-clusters)")
    print(f"  LEAKY: antigen cluster seen in our train: {len(b_leaky)} ({len({r['cluster_id'] for r in b_leaky})} our-clusters)")
    print(f"  CLEAN: antigen cluster unseen in train  : {len(b_clean)} ({len({r['cluster_id'] for r in b_clean})} our-clusters)")

    # ---------------- candidate arms --------------------------------------
    print("\n=== CANDIDATE ARMS (all are subsets of OUR already-read test split) ===")
    arm_defs = {
        "ARM-1_their_test_partition": [r for r in test_rows
                                       if rec_of.get(r["instance_id"], {}).get("abag_split") == "test"],
        "ARM-2_abag_cluster_clean": a_clean,
        "ARM-3_antigen_cluster_clean": b_clean,
        "ARM-4_intersection_2and3": [r for r in a_clean if r in b_clean],
    }
    for name, arm in arm_defs.items():
        cl = {r["cluster_id"] for r in arm}
        print(f"  {name:30s}: {len(arm):5d} instances  {len(cl):4d} our antigen clusters")
        path = f"{OUT_DIR}/{name}.csv"
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["instance_id", "pdb_id", "antigen_chains", "our_cluster_id",
                        "n_epitope", "sabdab2_abag_cluster", "sabdab2_abag_split"])
            for r in sorted(arm, key=lambda x: x["instance_id"]):
                rec = rec_of.get(r["instance_id"], {})
                w.writerow([r["instance_id"], r["pdb_id"], r["antigen_chains"], r["cluster_id"],
                            r["n_epitope"], rec.get("abag_cluster", ""), rec.get("abag_split", "")])

    # cluster-size sanity: macro-average is over clusters, so report the spread
    sizes = collections.Counter()
    for r in arm_defs["ARM-3_antigen_cluster_clean"]:
        sizes[r["cluster_id"]] += 1
    if sizes:
        v = sorted(sizes.values())
        print(f"\nARM-3 instances per our-cluster: min={v[0]} median={v[len(v)//2]} max={v[-1]} "
              f"(macro-average denominator = {len(v)} clusters)")


if __name__ == "__main__":
    main()
