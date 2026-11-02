"""Combine Protenix and Boltz-2 evidence to filter RBX1 candidates.

Reads:
  - <design-dir>/seed_NNN/csv_line.txt  (Vast.ai single nesting)
  - <design-dir>/seed_NNN/seed_NNN/csv_line.txt  (Modal double nesting)
  - <boltz2-csv> (Boltz2 metrics)

Usage:
    python filter_rbx1.py
    python filter_rbx1.py --design-dir vast_outputs_rbx1 --boltz2-csv vast_boltz2_outputs/boltz2_summary.csv"""

import argparse
import csv
from pathlib import Path

# Thresholds from spec
THRESH_CYS = 0
THRESH_BINDER_PLDDT = 0.85
THRESH_B2_PLDDT = 0.75
THRESH_B2_IPSAE = 0.80
THRESH_B2_MIN_IPSAE = 0.65
THRESH_B2_IPTM = 0.85

SEEDS = [0, 4, 7, 8, 9, 10, 11, 12, 15, 16, 17, 19]


def main():
    parser = argparse.ArgumentParser(description="RBX1 candidate filtering")
    parser.add_argument(
        "--design-dir",
        default="modal_outputs_2lgv",
        help="Directory with seed_NNN/ design outputs (default: modal_outputs_2lgv)",
    )
    parser.add_argument(
        "--boltz2-csv",
        default="boltz2_outputs_2lgv/boltz2_summary.csv",
        help="Boltz2 validation summary CSV (default: boltz2_outputs_2lgv/boltz2_summary.csv)",
    )
    args = parser.parse_args()

    # --- Read Protenix design metrics ---
    protenix_data = {}
    design_dir = Path(args.design_dir)
    for seed in SEEDS:
        # Try Vast.ai layout (single nesting): design_dir/seed_NNN/csv_line.txt
        csv_path = design_dir / f"seed_{seed:03d}" / "csv_line.txt"
        if not csv_path.exists():
            # Try Modal layout (double nesting): design_dir/seed_NNN/seed_NNN/csv_line.txt
            csv_path = design_dir / f"seed_{seed:03d}" / f"seed_{seed:03d}" / "csv_line.txt"
        if csv_path.exists():
            parts = csv_path.read_text().strip().split(",")
            # Format: seed, sequence, length, cys_count, binder_plddt, target_plddt, iptm
            protenix_data[seed] = {
                "sequence": parts[1],
                "length": int(parts[2]),
                "cys_count": int(parts[3]),
                "binder_plddt": float(parts[4]),
                "target_plddt": float(parts[5]),
                "protenix_iptm": float(parts[6]),
            }

    # --- Read Boltz2 validation metrics ---
    boltz2_data = {}
    b2_csv = Path(args.boltz2_csv)
    if b2_csv.exists():
        with open(b2_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                seed = int(row["seed"])
                bt = float(row["boltz2_bt_ipsae"])
                tb = float(row["boltz2_tb_ipsae"])
                boltz2_data[seed] = {
                    "b2_plddt": float(row["boltz2_plddt"]),
                    "b2_iptm": float(row["boltz2_iptm"]),
                    "b2_bt_ipsae": bt,
                    "b2_tb_ipsae": tb,
                    "b2_ipsae": max(bt, tb),
                    "b2_min_ipsae": float(row["boltz2_min_ipsae"]),
                }
    else:
        print(f"ERROR: {b2_csv} not found. Run modal_boltz2.py first.")
        print("If results are on the volume, download with:")
        print("  modal volume get mosaic-weights boltz2_outputs/ boltz2_outputs_2lgv/")
        exit(1)

    # --- Combine and filter ---
    print("=" * 95)
    print("RBX1 Minibinder Candidate Filtering")
    print("=" * 95)
    print()
    print(f"{'Seed':>5s}  {'Cys':>3s}  {'pLDDT':>7s}  {'B2_pLDDT':>8s}  "
          f"{'B2_ipSAE':>8s}  {'B2_min':>8s}  {'B2_ipTM':>8s}  Status")
    print("-" * 95)

    survivors = []
    for seed in SEEDS:
        if seed not in protenix_data:
            print(f"  {seed:>3d}  {'?':>3s}  {'?':>7s}  {'?':>8s}  "
                  f"{'?':>8s}  {'?':>8s}  {'?':>8s}  MISSING PROTENIX")
            continue

        p = protenix_data[seed]

        if seed not in boltz2_data:
            print(f"  {seed:>3d}  {p['cys_count']:>3d}  {p['binder_plddt']:>7.3f}  {'?':>8s}  "
                  f"{'?':>8s}  {'?':>8s}  {'?':>8s}  MISSING BOLTZ2")
            continue

        b = boltz2_data[seed]

        # Apply filter cascade
        fails = []
        if p["cys_count"] > THRESH_CYS:
            fails.append("CYS")
        if p["binder_plddt"] <= THRESH_BINDER_PLDDT:
            fails.append("pLDDT")
        if b["b2_plddt"] <= THRESH_B2_PLDDT:
            fails.append("b2pLDDT")
        if b["b2_ipsae"] <= THRESH_B2_IPSAE:
            fails.append("ipSAE")
        if b["b2_min_ipsae"] <= THRESH_B2_MIN_IPSAE:
            fails.append("min_ip")
        if b["b2_iptm"] <= THRESH_B2_IPTM:
            fails.append("ipTM")

        status = "PASS" if not fails else ", ".join(fails)
        print(f"  {seed:>3d}  {p['cys_count']:>3d}  {p['binder_plddt']:>7.3f}  {b['b2_plddt']:>8.3f}  "
              f"{b['b2_ipsae']:>8.3f}  {b['b2_min_ipsae']:>8.3f}  {b['b2_iptm']:>8.3f}  {status}")

        if not fails:
            survivors.append({"seed": seed, **p, **b})

    # --- Rank survivors ---
    survivors.sort(key=lambda x: (-x["b2_ipsae"], -x["b2_min_ipsae"]))

    print()
    print("=" * 95)
    print(f"Survivors: {len(survivors)} of {len(SEEDS)}")
    print("=" * 95)

    if survivors:
        print()
        print(f"{'Rank':>4s}  {'Seed':>5s}  {'ipSAE':>7s}  {'min_ip':>7s}  {'ipTM':>7s}  "
              f"{'pLDDT':>7s}  {'B2_pLDDT':>8s}  Sequence")
        print("-" * 95)
        for i, s in enumerate(survivors, 1):
            print(f"  {i:>2d}   {s['seed']:>3d}   {s['b2_ipsae']:>7.3f}  {s['b2_min_ipsae']:>7.3f}  "
                  f"{s['b2_iptm']:>7.3f}  {s['binder_plddt']:>7.3f}  {s['b2_plddt']:>8.3f}  "
                  f"{s['sequence'][:30]}...")

        top5 = survivors[:5]
        print()
        print(f"Recommended top {min(5, len(survivors))}: "
              + ", ".join(f"seed {s['seed']}" for s in top5))
    else:
        print("\nNo candidates survived all filters.")
        print("Consider relaxing thresholds or generating more candidates.")

    print()


if __name__ == "__main__":
    main()
