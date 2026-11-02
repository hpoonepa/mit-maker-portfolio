"""Cross-map PRINCE's antigen-clustered benchmark onto the SAbDab2 published splits.

Usage:
  python -I crossmap.py <abag_split.csv> <ab_split.csv> <prince_manifest.csv>

Treats the SAbDab2 CSVs as untrusted data: parsed with the stdlib csv reader only.
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import collections
import csv
import sys

csv.field_size_limit(1 << 30)


def norm_pdb(v: str) -> str:
    """pdb_00001ejo -> 1ejo ; 1ejo -> 1ejo."""
    v = v.strip().lower()
    if v.startswith("pdb_") and len(v) > 4:
        v = v[4:].lstrip("0")
    return v


def load_sabdab2(path: str, split_col: str, cluster_col: str) -> dict:
    """Return {(pdb4, hchain, lchain): {split, cluster, agchains, instance}}."""
    out = {}
    with open(path, newline="") as fh:
        rdr = csv.DictReader(fh)
        for row in rdr:
            pdb = norm_pdb(row["PDB_ID"])
            h = (row.get("Hchain") or "").strip()
            l = (row.get("Lchain") or "").strip()
            out[(pdb, h, l)] = {
                "split": (row.get(split_col) or "").strip(),
                "cluster": (row.get(cluster_col) or "").strip(),
                "agchains": (row.get("agchains") or "").strip(),
                "holo": (row.get("holo") or "").strip(),
                "type": (row.get("type") or "").strip(),
                "sabdab_id": (row.get("SABDAB_ID") or "").strip(),
                "instance": (row.get("INSTANCE") or "").strip(),
            }
    return out


def main() -> None:
    abag_path, ab_path, manifest_path = sys.argv[1], sys.argv[2], sys.argv[3]

    abag = load_sabdab2(abag_path, "ab_ag_split", "ab_ag_cluster")
    print(f"[abag] rows={len(abag)}  split values={collections.Counter(v['split'] for v in abag.values())}")
    ab = load_sabdab2(ab_path, "ab_split", "ab_cluster")
    print(f"[ab]   rows={len(ab)}  split values={collections.Counter(v['split'] for v in ab.values())}")

    by_pdb = collections.defaultdict(set)
    for (pdb, h, l) in abag:
        by_pdb[pdb].add((h, l))

    ours = list(csv.DictReader(open(manifest_path, newline="")))
    print(f"[ours] rows={len(ours)}  clusters={len({r['cluster_id'] for r in ours})}  pdbs={len({r['pdb_id'] for r in ours})}")

    # ---- chain-level and pdb-level matching --------------------------------
    matched_exact = {}       # instance_id -> their record (abag)
    matched_pdb_only = []    # instance_id present by pdb but chain pair absent
    unmatched_pdb = []       # pdb absent from their resource entirely
    for r in ours:
        pdb = norm_pdb(r["pdb_id"])
        key = (pdb, r["heavy_chain"].strip(), r["light_chain"].strip())
        if key in abag:
            matched_exact[r["instance_id"]] = abag[key]
        elif pdb in by_pdb:
            matched_pdb_only.append(r["instance_id"])
        else:
            unmatched_pdb.append(r["instance_id"])

    print("\n=== COVERAGE (our 6,937 instances vs SAbDab2 abag table) ===")
    print(f"exact (pdb+Hchain+Lchain) match : {len(matched_exact)}")
    print(f"pdb present, chain pair absent  : {len(matched_pdb_only)}")
    print(f"pdb absent from resource        : {len(unmatched_pdb)}")
    our_pdbs = {norm_pdb(r['pdb_id']) for r in ours}
    print(f"our pdb ids present in theirs   : {len(our_pdbs & set(by_pdb))} / {len(our_pdbs)}")
    our_cl_matched = {r['cluster_id'] for r in ours if r['instance_id'] in matched_exact}
    print(f"our antigen clusters with >=1 matched instance : {len(our_cl_matched)} / {len({r['cluster_id'] for r in ours})}")

    # ---- confusion table: our split x their abag partition ----------------
    def confusion(table: dict, label: str) -> None:
        print(f"\n=== CONFUSION: our split (rows) x SAbDab2 {label} partition (cols), instance counts ===")
        cm = collections.Counter()
        for r in ours:
            pdb = norm_pdb(r["pdb_id"])
            key = (pdb, r["heavy_chain"].strip(), r["light_chain"].strip())
            theirs = table.get(key, {}).get("split", "<unmatched>") or "<blank>"
            cm[(r["split"], theirs)] += 1
        theirvals = sorted({k[1] for k in cm})
        ourvals = ["train", "val", "test"]
        w = max(len(t) for t in theirvals) + 2
        print("our\\theirs".ljust(12) + "".join(t.rjust(w) for t in theirvals) + "total".rjust(w))
        for ov in ourvals:
            row = [cm[(ov, tv)] for tv in theirvals]
            print(ov.ljust(12) + "".join(str(c).rjust(w) for c in row) + str(sum(row)).rjust(w))
        tot = [sum(cm[(ov, tv)] for ov in ourvals) for tv in theirvals]
        print("total".ljust(12) + "".join(str(c).rjust(w) for c in tot) + str(sum(tot)).rjust(w))

    confusion(abag, "ab-ag")
    confusion(ab, "ab-only")

    # ---- our clusters straddling their partitions -------------------------
    print("\n=== OUR CLUSTER COHERENCE UNDER THEIR ab-ag PARTITION ===")
    cl_parts = collections.defaultdict(set)
    for r in ours:
        if r["instance_id"] in matched_exact:
            s = matched_exact[r["instance_id"]]["split"]
            cl_parts[r["cluster_id"]].add(s)
    straddle = {c: p for c, p in cl_parts.items() if len(p) > 1}
    print(f"our clusters with >=1 matched instance : {len(cl_parts)}")
    print(f"  land entirely in ONE of their partitions : {len(cl_parts) - len(straddle)}")
    print(f"  STRADDLE >=2 of their partitions         : {len(straddle)}")
    print("  straddle pattern counts:", collections.Counter(tuple(sorted(p)) for p in straddle.values()))

    # reverse: their abag cluster vs our splits
    print("\n=== THEIR ab-ag CLUSTER COHERENCE UNDER OUR SPLIT ===")
    their_cl = collections.defaultdict(set)
    for r in ours:
        rec = matched_exact.get(r["instance_id"])
        if rec and rec["cluster"]:
            their_cl[rec["cluster"]].add(r["split"])
    th_straddle = {c: p for c, p in their_cl.items() if len(p) > 1}
    print(f"their ab-ag clusters touched by our data : {len(their_cl)}")
    print(f"  entirely inside one of our splits      : {len(their_cl) - len(th_straddle)}")
    print(f"  STRADDLE >=2 of our splits             : {len(th_straddle)}")
    print("  straddle pattern counts:", collections.Counter(tuple(sorted(p)) for p in th_straddle.values()))

    # ---- the candidate sensitivity arm ------------------------------------
    print("\n=== CANDIDATE SENSITIVITY ARM (our instances in THEIR ab-ag test partition) ===")
    for want in sorted({v["split"] for v in abag.values()}):
        arm = [r for r in ours if matched_exact.get(r["instance_id"], {}).get("split") == want]
        if not arm:
            continue
        armcl = {r["cluster_id"] for r in arm}
        oursplit = collections.Counter(r["split"] for r in arm)
        print(f"  their '{want}': {len(arm)} our-instances, {len(armcl)} of our antigen clusters, our-split mix={dict(oursplit)}")
        # strict arm: also unseen by our training
        strict = [r for r in arm if r["split"] != "train"]
        print(f"      strict (excluding anything in OUR train): {len(strict)} instances, {len({r['cluster_id'] for r in strict})} clusters")
        strict_test = [r for r in arm if r["split"] == "test"]
        print(f"      intersection with OUR test split        : {len(strict_test)} instances, {len({r['cluster_id'] for r in strict_test})} clusters")

    # write the arm membership
    out_arm = str(DATA / "sabdab2/abag_test_arm.csv")
    with open(out_arm, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["instance_id", "pdb_id", "heavy_chain", "light_chain", "antigen_chains",
                    "our_cluster_id", "our_split", "sabdab2_instance", "sabdab2_id",
                    "sabdab2_abag_cluster", "sabdab2_abag_split", "sabdab2_ab_split"])
        for r in ours:
            rec = matched_exact.get(r["instance_id"])
            if not rec:
                continue
            key = (norm_pdb(r["pdb_id"]), r["heavy_chain"].strip(), r["light_chain"].strip())
            w.writerow([r["instance_id"], r["pdb_id"], r["heavy_chain"], r["light_chain"],
                        r["antigen_chains"], r["cluster_id"], r["split"], rec["instance"],
                        rec["sabdab_id"], rec["cluster"], rec["split"],
                        ab.get(key, {}).get("split", "")])
    print(f"\nwrote joined table: {out_arm}")


if __name__ == "__main__":
    main()
