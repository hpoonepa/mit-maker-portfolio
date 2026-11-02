"""Measure the selected hotspot contacts in each completed V5 design.

For each seed:
  - parse seed_NNN_complex.pdb
  - get CA atoms of chain A (binder, 85 residues)
  - identify chain B residues at 0-indexed positions 145 and 148 (the hotspots)
  - compute the minimum binder-CA -> hotspot-CA distance per hotspot
  - print a table sortable by min hotspot distance"""
from __future__ import annotations
import math
import json
from pathlib import Path

OUTROOT = Path(__file__).parent / "outputs" / "5g51_v5_hotspots"
HOTSPOTS = [145, 148]   # 0-indexed positions in chain B
DIST_THRESHOLD = 8.0    # Å — same as the loss's distance_threshold

# 3-letter -> 1-letter amino acid
AA3 = {"ALA":"A","CYS":"C","ASP":"D","GLU":"E","PHE":"F","GLY":"G","HIS":"H",
       "ILE":"I","LYS":"K","LEU":"L","MET":"M","ASN":"N","PRO":"P","GLN":"Q",
       "ARG":"R","SER":"S","THR":"T","VAL":"V","TRP":"W","TYR":"Y","UNK":"X"}


def parse_pdb(path: Path):
    """Return (chain_A_CAs, chain_B_residues) where the latter is an ordered
    list of (resnum, resname, ca_coord) tuples."""
    chain_a_cas: list[tuple[float, float, float]] = []
    chain_b_res: list[tuple[int, str, tuple[float, float, float]]] = []
    seen_b: dict[int, tuple[str, tuple[float, float, float]]] = {}
    seen_a_resnums: set[int] = set()
    with open(path) as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            atom = line[12:16].strip()
            if atom != "CA":
                continue
            chain = line[21]
            resnum = int(line[22:26].strip())
            resname = line[17:20].strip()
            x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
            if chain == "A":
                if resnum not in seen_a_resnums:
                    seen_a_resnums.add(resnum)
                    chain_a_cas.append((x, y, z))
            elif chain == "B":
                if resnum not in seen_b:
                    seen_b[resnum] = (resname, (x, y, z))
    chain_b_res = [(rn, seen_b[rn][0], seen_b[rn][1]) for rn in sorted(seen_b)]
    return chain_a_cas, chain_b_res


def dist(a, b) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def main():
    seed_dirs = sorted(d for d in OUTROOT.iterdir() if d.name.startswith("seed_"))
    print(f"{'seed':>4} {'iPTM':>6} {'bPLDDT':>7} "
          f"{'h145(ILE)':>11} {'h148(PHE)':>11} "
          f"{'min':>6} {'verdict':<10}")
    print("-" * 72)

    rows = []
    for d in seed_dirs:
        meta = json.loads((d / f"{d.name}_meta.json").read_text())
        pdb_path = d / f"{d.name}_complex.pdb"
        if not pdb_path.exists():
            print(f"{meta['seed']:>4} (missing PDB)")
            continue
        binder_cas, target_res = parse_pdb(pdb_path)

        # Look up hotspots by 0-indexed position
        hs_dists = []
        hs_idents = []
        for idx in HOTSPOTS:
            if idx >= len(target_res):
                hs_dists.append(float("inf"))
                hs_idents.append(f"?{idx}")
                continue
            _, resname, ca = target_res[idx]
            d_min = min(dist(b, ca) for b in binder_cas)
            hs_dists.append(d_min)
            hs_idents.append(f"{AA3.get(resname,'X')}{idx}")

        min_d = min(hs_dists)
        if min_d < DIST_THRESHOLD:
            verdict = "HOTSPOT"
        elif min_d < 12.0:
            verdict = "near"
        else:
            verdict = "missed"

        rows.append((min_d, meta["seed"], meta["iptm"], meta["binder_plddt"],
                     hs_dists, hs_idents, verdict))

    # Sort by best (smallest min distance)
    for min_d, seed, iptm, bplddt, hs_dists, hs_idents, verdict in sorted(rows):
        h_str = " ".join(f"{ident}={d:5.1f}Å" if not math.isinf(d) else f"{ident}=  oob"
                         for ident, d in zip(hs_idents, hs_dists))
        print(f"{seed:>4} {iptm:>6.3f} {bplddt:>7.3f} {h_str}  "
              f"{min_d:>5.1f} {verdict:<10}")

    # Identity check: do positions 145 and 148 in chain B map to ILE / PHE?
    if rows:
        _, first_resname_145 = None, None
        sample = seed_dirs[0]
        binder_cas, target_res = parse_pdb(sample / f"{sample.name}_complex.pdb")
        print(f"\nIdentity check (chain B, 0-indexed): "
              f"{HOTSPOTS[0]}={AA3.get(target_res[HOTSPOTS[0]][1],'?')} "
              f"({target_res[HOTSPOTS[0]][1]}) "
              f"({'OK' if target_res[HOTSPOTS[0]][1]=='ILE' else 'MISMATCH — expected ILE'}); "
              f"{HOTSPOTS[1]}={AA3.get(target_res[HOTSPOTS[1]][1],'?')} "
              f"({target_res[HOTSPOTS[1]][1]}) "
              f"({'OK' if target_res[HOTSPOTS[1]][1]=='PHE' else 'MISMATCH — expected PHE'})")


if __name__ == "__main__":
    main()
