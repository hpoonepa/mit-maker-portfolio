"""Pick the best V5+hotspot designs from the 11 completed seeds and write a
ranked CSV. Composite score weights interface confidence (iPTM 40%, pLDDT 20%)
and hotspot engagement (40%): the whole point of the hotspot loss was that
geometry beats raw iPTM."""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path

OUTROOT = Path(__file__).parent / "outputs" / "5g51_v5_hotspots"
HOTSPOTS = [145, 148]      # 0-indexed positions in chain B
CONTACT_THRESHOLD = 8.0    # Å — matches the loss's distance_threshold

AA3 = {"ALA":"A","CYS":"C","ASP":"D","GLU":"E","PHE":"F","GLY":"G","HIS":"H",
       "ILE":"I","LYS":"K","LEU":"L","MET":"M","ASN":"N","PRO":"P","GLN":"Q",
       "ARG":"R","SER":"S","THR":"T","VAL":"V","TRP":"W","TYR":"Y","UNK":"X"}


def parse_pdb(path: Path):
    binder_cas: list[tuple[float, float, float]] = []
    target_res: list[tuple[int, str, tuple[float, float, float]]] = []
    seen_b: dict[int, tuple[str, tuple[float, float, float]]] = {}
    seen_a: set[int] = set()
    with open(path) as f:
        for line in f:
            if not line.startswith("ATOM") or line[12:16].strip() != "CA":
                continue
            chain = line[21]
            resnum = int(line[22:26].strip())
            resname = line[17:20].strip()
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            if chain == "A" and resnum not in seen_a:
                seen_a.add(resnum); binder_cas.append(xyz)
            elif chain == "B" and resnum not in seen_b:
                seen_b[resnum] = (resname, xyz)
    target_res = [(rn, seen_b[rn][0], seen_b[rn][1]) for rn in sorted(seen_b)]
    return binder_cas, target_res


def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def hotspot_quality(d145: float, d148: float) -> float:
    """[0..1] continuous score: rewards both hotspots within threshold, partial
    credit for one, sharp penalty when >12 Å."""
    def one(d):
        if d <= 5.0: return 1.0           # tight contact
        if d <= 8.0: return 0.8           # within threshold
        if d <= 12.0: return 0.3          # near but not contact
        return 0.0                         # missed
    return 0.5 * (one(d145) + one(d148))


def recommendation(iptm, plddt, d145, d148, cys):
    both_contact = d145 <= CONTACT_THRESHOLD and d148 <= CONTACT_THRESHOLD
    any_contact = d145 <= CONTACT_THRESHOLD or d148 <= CONTACT_THRESHOLD
    if iptm >= 0.5 and plddt >= 0.7 and both_contact and cys == 0:
        return "TOP — order"
    if iptm >= 0.5 and any_contact and cys == 0:
        return "good — backup"
    if both_contact and iptm >= 0.4:
        return "geometric — risk on affinity"
    if not any_contact:
        return "off-target — skip"
    return "weak — skip"


def main():
    rows = []
    for d in sorted(OUTROOT.iterdir()):
        if not d.name.startswith("seed_"):
            continue
        meta_path = d / f"{d.name}_meta.json"
        pdb_path = d / f"{d.name}_complex.pdb"
        if not (meta_path.exists() and pdb_path.exists()):
            continue
        meta = json.loads(meta_path.read_text())
        binder_cas, target_res = parse_pdb(pdb_path)
        d145 = min(dist(b, target_res[145][2]) for b in binder_cas)
        d148 = min(dist(b, target_res[148][2]) for b in binder_cas)

        iptm = meta["iptm"]
        bplddt = meta["binder_plddt"]
        tplddt = meta["target_plddt"]
        cys = meta["cysteine_count"]
        composite = 0.4 * iptm + 0.2 * bplddt + 0.4 * hotspot_quality(d145, d148)

        rows.append({
            "seed": meta["seed"],
            "sequence": meta["designed_sequence"],
            "length": meta["binder_length"],
            "cys_count": cys,
            "iptm": round(iptm, 4),
            "binder_plddt": round(bplddt, 4),
            "target_plddt": round(tplddt, 4),
            "ile145_dist_angstrom": round(d145, 2),
            "phe148_dist_angstrom": round(d148, 2),
            "both_hotspots_contacted": d145 <= CONTACT_THRESHOLD and d148 <= CONTACT_THRESHOLD,
            "composite_score": round(composite, 4),
            "recommendation": recommendation(iptm, bplddt, d145, d148, cys),
        })

    # Sort by composite score, descending
    rows.sort(key=lambda r: -r["composite_score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # Write the full ranked CSV
    out_full = OUTROOT.parent / "5g51_v5_best_sequences.csv"
    cols = ["rank", "seed", "recommendation", "composite_score", "iptm",
            "binder_plddt", "target_plddt", "ile145_dist_angstrom",
            "phe148_dist_angstrom", "both_hotspots_contacted",
            "cys_count", "length", "sequence"]
    with open(out_full, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})

    # And a simple top-picks CSV with just rank/seed/sequence for ordering
    top = [r for r in rows if r["recommendation"].startswith(("TOP", "good"))]
    out_top = OUTROOT.parent / "5g51_v5_top_picks.csv"
    with open(out_top, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "seed", "name", "sequence"])
        for r in top:
            name = f"5G51_V5_seed{r['seed']:02d}_rank{r['rank']}"
            w.writerow([r["rank"], r["seed"], name, r["sequence"]])

    # Print a console summary
    print(f"\nWrote {out_full}")
    print(f"Wrote {out_top}  ({len(top)} picks)\n")
    print(f"{'rank':>4} {'seed':>4} {'iPTM':>6} {'bPLDDT':>7} "
          f"{'I145':>6} {'F148':>6} {'comp':>6}  {'recommendation':<32}")
    print("-" * 80)
    for r in rows:
        print(f"{r['rank']:>4} {r['seed']:>4} {r['iptm']:>6.3f} "
              f"{r['binder_plddt']:>7.3f} {r['ile145_dist_angstrom']:>6.1f} "
              f"{r['phe148_dist_angstrom']:>6.1f} {r['composite_score']:>6.3f}  "
              f"{r['recommendation']:<32}")


if __name__ == "__main__":
    main()
