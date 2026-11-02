"""Filter candidates by structure scores and sequence properties.

Usage:
    python filter_god.py
    python filter_god.py --design-dir god_outputs --boltz2-csv boltz2_god_summary.csv"""

import csv
import argparse
import math
from pathlib import Path
from collections import Counter

# --- Proteinbase-optimized thresholds (tighter than filter_rbx1.py) ---

# Structural thresholds
THRESH_CYS = 0                   # Zero tolerance for cysteines
THRESH_BINDER_PLDDT = 0.90       # 0.85 -> 0.90 (top designs hit 0.95+)
THRESH_B2_PLDDT = 0.80           # 0.75 -> 0.80 (Boltz2 confidence)
THRESH_B2_IPSAE = 0.85           # 0.80 -> 0.85 (most predictive metric)
THRESH_B2_MIN_IPSAE = 0.70       # 0.65 -> 0.70 (directional minimum)
THRESH_B2_IPTM = 0.90            # 0.85 -> 0.90 (strict interface quality)

# Sequence quality thresholds (from Proteinbase analysis)
THRESH_GLYCINE_MAX = 0.10        # High glycine = worse binding (AUC=0.625)
THRESH_GLUTAMATE_MIN = 0.08      # Negative charge correlates with binding (AUC=0.594)
THRESH_HYDROPHOBIC_MIN = 0.30    # Optimal hydrophobic range
THRESH_HYDROPHOBIC_MAX = 0.50    # Optimal hydrophobic range
THRESH_SEQ_ENTROPY_MAX = 4.0     # Lower entropy = more designed

# Amino acid property sets
HYDROPHOBIC = set("AILMFWVP")
CHARGED_NEG = set("DE")


def compute_seq_features(sequence):
    """Compute sequence-level features from amino acid sequence."""
    n = len(sequence)
    counts = Counter(sequence)

    # Fractions
    glycine_frac = counts.get("G", 0) / n
    glutamate_frac = counts.get("E", 0) / n
    hydrophobic_frac = sum(counts.get(aa, 0) for aa in HYDROPHOBIC) / n
    charged_neg_frac = sum(counts.get(aa, 0) for aa in CHARGED_NEG) / n

    # Shannon entropy
    freqs = [c / n for c in counts.values() if c > 0]
    entropy = -sum(f * math.log2(f) for f in freqs)

    return {
        "glycine_frac": glycine_frac,
        "glutamate_frac": glutamate_frac,
        "hydrophobic_frac": hydrophobic_frac,
        "charged_neg_frac": charged_neg_frac,
        "seq_entropy": entropy,
    }


def composite_score(p, b):
    """Compute composite god-score for ranking (higher = better)."""
    return (
        0.35 * b.get("b2_ipsae", 0)
        + 0.25 * b.get("b2_min_ipsae", 0)
        + 0.20 * b.get("b2_iptm", 0)
        + 0.10 * p.get("binder_plddt", 0)
        + 0.10 * b.get("b2_plddt", 0)
    )


def main():
    parser = argparse.ArgumentParser(description="God-tier binder filtering")
    parser.add_argument(
        "--design-dir",
        default="god_outputs",
        help="Directory with seed_NNN/csv_line.txt files",
    )
    parser.add_argument(
        "--boltz2-csv",
        default="boltz2_god_summary.csv",
        help="Boltz2 validation summary CSV",
    )
    parser.add_argument(
        "--output",
        default="god_filtered_candidates.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="Use relaxed thresholds (original filter_rbx1.py levels)",
    )
    args = parser.parse_args()

    # Allow relaxed mode for comparison
    if args.relaxed:
        global THRESH_BINDER_PLDDT, THRESH_B2_PLDDT, THRESH_B2_IPSAE
        global THRESH_B2_MIN_IPSAE, THRESH_B2_IPTM
        THRESH_BINDER_PLDDT = 0.85
        THRESH_B2_PLDDT = 0.75
        THRESH_B2_IPSAE = 0.80
        THRESH_B2_MIN_IPSAE = 0.65
        THRESH_B2_IPTM = 0.85
        print("Using RELAXED thresholds (original filter_rbx1.py levels)")

    design_dir = Path(args.design_dir)

    # --- Read Protenix design metrics ---
    protenix_data = {}
    for seed_dir in sorted(design_dir.glob("seed_*")):
        csv_path = seed_dir / "csv_line.txt"
        if not csv_path.exists():
            # Try nested pattern
            nested = list(seed_dir.glob("*/csv_line.txt"))
            if nested:
                csv_path = nested[0]
            else:
                continue

        parts = csv_path.read_text().strip().split(",")
        seed = int(parts[0])
        protenix_data[seed] = {
            "sequence": parts[1],
            "length": int(parts[2]),
            "cys_count": int(parts[3]),
            "binder_plddt": float(parts[4]),
            "target_plddt": float(parts[5]),
            "protenix_iptm": float(parts[6]),
        }

    print(f"Loaded {len(protenix_data)} Protenix designs from {design_dir}")

    # --- Read Boltz2 validation metrics ---
    boltz2_data = {}
    b2_csv = Path(args.boltz2_csv)
    if b2_csv.exists():
        with open(b2_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                seed = int(row["seed"])
                bt = float(row.get("boltz2_bt_ipsae", 0))
                tb = float(row.get("boltz2_tb_ipsae", 0))
                boltz2_data[seed] = {
                    "b2_plddt": float(row.get("boltz2_plddt", 0)),
                    "b2_iptm": float(row.get("boltz2_iptm", 0)),
                    "b2_bt_ipsae": bt,
                    "b2_tb_ipsae": tb,
                    "b2_ipsae": max(bt, tb),
                    "b2_min_ipsae": float(row.get("boltz2_min_ipsae", 0)),
                }
        print(f"Loaded {len(boltz2_data)} Boltz2 validations from {b2_csv}")
    else:
        print(f"WARNING: {b2_csv} not found. Filtering on Protenix metrics only.")

    # --- Combine and filter ---
    print()
    print("=" * 110)
    print("GOD-TIER Minibinder Candidate Filtering")
    print("=" * 110)
    print()
    print(
        f"{'Seed':>5s}  {'Cys':>3s}  {'pLDDT':>7s}  {'B2_pLDDT':>8s}  "
        f"{'B2_ipSAE':>8s}  {'B2_min':>8s}  {'B2_ipTM':>8s}  "
        f"{'Gly%':>5s}  {'Glu%':>5s}  {'Hphob%':>6s}  Status"
    )
    print("-" * 110)

    survivors = []
    all_seeds = sorted(set(list(protenix_data.keys()) + list(boltz2_data.keys())))

    for seed in all_seeds:
        if seed not in protenix_data:
            continue

        p = protenix_data[seed]
        seq_feat = compute_seq_features(p["sequence"])

        has_b2 = seed in boltz2_data
        b = boltz2_data.get(seed, {})

        # Apply filter cascade
        fails = []

        # Structural filters
        if p["cys_count"] > THRESH_CYS:
            fails.append("CYS")
        if p["binder_plddt"] <= THRESH_BINDER_PLDDT:
            fails.append("pLDDT")

        # Boltz2 filters (only if data available)
        if has_b2:
            if b.get("b2_plddt", 0) <= THRESH_B2_PLDDT:
                fails.append("b2pLDDT")
            if b.get("b2_ipsae", 0) <= THRESH_B2_IPSAE:
                fails.append("ipSAE")
            if b.get("b2_min_ipsae", 0) <= THRESH_B2_MIN_IPSAE:
                fails.append("min_ip")
            if b.get("b2_iptm", 0) <= THRESH_B2_IPTM:
                fails.append("ipTM")

        # Sequence quality filters
        if seq_feat["glycine_frac"] > THRESH_GLYCINE_MAX:
            fails.append("Gly")
        if seq_feat["glutamate_frac"] < THRESH_GLUTAMATE_MIN:
            fails.append("Glu")
        if not (THRESH_HYDROPHOBIC_MIN <= seq_feat["hydrophobic_frac"] <= THRESH_HYDROPHOBIC_MAX):
            fails.append("Hphob")

        status = "PASS" if not fails else ", ".join(fails)

        b2_plddt_str = f"{b.get('b2_plddt', 0):>8.3f}" if has_b2 else f"{'?':>8s}"
        b2_ipsae_str = f"{b.get('b2_ipsae', 0):>8.3f}" if has_b2 else f"{'?':>8s}"
        b2_min_str = f"{b.get('b2_min_ipsae', 0):>8.3f}" if has_b2 else f"{'?':>8s}"
        b2_iptm_str = f"{b.get('b2_iptm', 0):>8.3f}" if has_b2 else f"{'?':>8s}"

        print(
            f"  {seed:>3d}  {p['cys_count']:>3d}  {p['binder_plddt']:>7.3f}  "
            f"{b2_plddt_str}  {b2_ipsae_str}  {b2_min_str}  {b2_iptm_str}  "
            f"{seq_feat['glycine_frac']:>5.3f}  {seq_feat['glutamate_frac']:>5.3f}  "
            f"{seq_feat['hydrophobic_frac']:>6.3f}  {status}"
        )

        if not fails:
            survivors.append({
                "seed": seed,
                **p,
                **b,
                **seq_feat,
                "god_score": composite_score(p, b),
            })

    # --- Rank survivors by composite god-score ---
    survivors.sort(key=lambda x: -x["god_score"])

    print()
    print("=" * 110)
    print(f"Survivors: {len(survivors)} of {len(protenix_data)}")
    print("=" * 110)

    if survivors:
        print()
        print(
            f"{'Rank':>4s}  {'Seed':>5s}  {'Score':>6s}  {'ipSAE':>7s}  "
            f"{'min_ip':>7s}  {'ipTM':>7s}  {'pLDDT':>7s}  {'B2_pLDDT':>8s}  Sequence"
        )
        print("-" * 110)
        for i, s in enumerate(survivors, 1):
            print(
                f"  {i:>2d}   {s['seed']:>3d}   {s['god_score']:>6.3f}  "
                f"{s.get('b2_ipsae', 0):>7.3f}  {s.get('b2_min_ipsae', 0):>7.3f}  "
                f"{s.get('b2_iptm', 0):>7.3f}  {s['binder_plddt']:>7.3f}  "
                f"{s.get('b2_plddt', 0):>8.3f}  {s['sequence'][:30]}..."
            )

        top = min(10, len(survivors))
        print()
        print(f"Top {top} for experimental validation:")
        print(", ".join(f"seed {s['seed']}" for s in survivors[:top]))

        # --- Save CSV ---
        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank", "model", "seed", "sequence", "length", "cys_count",
                "binder_plddt", "target_plddt", "design_iptm",
                "boltz2_iptm", "boltz2_ipsae", "boltz2_min_ipsae", "boltz2_plddt",
                "glycine_frac", "glutamate_frac", "hydrophobic_frac",
                "god_score", "filter_status",
            ])
            for i, s in enumerate(survivors, 1):
                writer.writerow([
                    i, "protenix", s["seed"], s["sequence"], s["length"],
                    s["cys_count"], f"{s['binder_plddt']:.4f}",
                    f"{s.get('target_plddt', 0):.4f}",
                    f"{s.get('protenix_iptm', 0):.4f}",
                    f"{s.get('b2_iptm', 0):.4f}",
                    f"{s.get('b2_ipsae', 0):.4f}",
                    f"{s.get('b2_min_ipsae', 0):.4f}",
                    f"{s.get('b2_plddt', 0):.4f}",
                    f"{s['glycine_frac']:.4f}",
                    f"{s['glutamate_frac']:.4f}",
                    f"{s['hydrophobic_frac']:.4f}",
                    f"{s['god_score']:.4f}",
                    "PASS",
                ])

        print(f"\nSaved {len(survivors)} candidates to {args.output}")
    else:
        print("\nNo candidates survived all god-tier filters.")
        print("Consider: python filter_god.py --relaxed")

    print()


if __name__ == "__main__":
    main()
