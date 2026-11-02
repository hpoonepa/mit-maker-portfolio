"""Vast.ai app: 5G51 minibinder design campaign on GPU.

Vast.ai equivalent of modal_5g51.py — runs the exact Protenix2025 +
ProteinMPNN + simplex_APGM workflow targeting PDB 5G51. Launches N seeds
in parallel via Vast.ai multi-instance orchestration.

Usage:
    python -m vast.vast_5g51                          # 50 seeds (default)
    python -m vast.vast_5g51 --num-seeds 100          # 100 seeds
    python -m vast.vast_5g51 --resume                 # resume interrupted campaign
    python -m vast.vast_5g51 --max-concurrent 5       # limit concurrency
"""

import argparse
import csv
import pathlib

from . import config
from . import orchestrator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMPAIGN_ID = "5g51-design"
OUTPUT_FILES = [
    "5g51_complex.pdb",
    "5g51_pssm.png",
    "5g51_pae.png",
    "5g51_plddt.png",
]
CSV_HEADER = [
    "seed", "sequence", "length", "cys_count",
    "binder_plddt", "target_plddt", "iptm",
]
DEFAULT_OUTPUT_DIR = "vast_outputs_5g51"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="5G51 binder design campaign on Vast.ai",
    )
    parser.add_argument(
        "--num-seeds", type=int, default=50,
        help="Number of design seeds to run (default: 50)",
    )
    parser.add_argument(
        "--resume", action="store_true", default=True,
        help="Resume from checkpoint if available (default: True)",
    )
    parser.add_argument(
        "--no-resume", dest="resume", action="store_false",
        help="Start fresh, ignoring any existing checkpoint",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=None,
        help=f"Max simultaneous instances (default: {config.MAX_CONCURRENT})",
    )
    parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"Local output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    num_seeds = args.num_seeds
    out = pathlib.Path(args.output_dir)

    print("=== 5G51 Binder Design Campaign (Vast.ai) ===")
    print(f"Seeds: {num_seeds}")
    print(f"GPU: {config.GPU_NAME}")
    print(f"Target: PDB 5G51 (VP3 P-domain, Deformed Wing Virus)")
    print(f"Binder length: 75 residues")
    print(f"Pipeline: Protenix2025 + ProteinMPNN + simplex_APGM")
    print(f"Docker image: {config.DOCKER_IMAGE_DESIGN}")
    print(f"Max price: ${config.MAX_PRICE_PER_HOUR:.2f}/hr")
    print(f"Resume: {args.resume}")
    print(f"Output: {out}")
    print()

    seeds = list(range(num_seeds))

    # Launch campaign via orchestrator
    results = orchestrator.map_seeds(
        campaign_id=CAMPAIGN_ID,
        docker_image=config.DOCKER_IMAGE_DESIGN,
        seeds=seeds,
        output_dir=str(out),
        extra_env={"DESIGN_SCRIPT": "design_5g51.py"},
        max_concurrent=args.max_concurrent,
        resume=args.resume,
    )

    # Separate successes and failures
    successes = [r for r in results if "error" not in r]
    failures = [r for r in results if "error" in r]

    # Write campaign summary CSV
    csv_path = out / "campaign_summary.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for res in successes:
            if res.get("csv_line"):
                writer.writerow(res["csv_line"].split(","))

    # Print summary
    print(f"\n=== Campaign Complete ===")
    print(f"Successes: {len(successes)}/{num_seeds}")
    print(f"Failures: {len(failures)}/{num_seeds}")
    print(f"Summary CSV: {csv_path}")
    print(f"Results: {out}/")

    # Quality preview
    if successes:
        print(f"\n=== Quality Preview ===")
        for res in successes:
            if res.get("csv_line"):
                parts = res["csv_line"].split(",")
                if len(parts) >= 7:
                    print(
                        f"  seed={parts[0]:>3s}  "
                        f"pLDDT={parts[4]}  "
                        f"ipTM={parts[6]}  "
                        f"cys={parts[3]}"
                    )

    print(f"\nNext: filter candidates with Boltz2 cross-validation (same as RBX1)")


if __name__ == "__main__":
    main()
