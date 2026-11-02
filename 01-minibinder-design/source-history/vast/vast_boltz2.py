"""Vast.ai Boltz2 validation for RBX1 candidates.

Equivalent of modal_boltz2.py — validates top Protenix candidates with Boltz2
on Vast.ai instead of Modal. Uses orchestrator.starmap_candidates() to launch
one instance per candidate in parallel.

Output structure:
    <output_dir>/
        seed_NNN/
            log.txt
            2lgv_boltz2.pdb
            csv_line.txt
    boltz2_summary.csv
"""

import argparse
import csv
import pathlib
import sys

from . import config
from . import orchestrator

# RBX1 target sequence (108aa construct)
RBX1_TARGET_SEQ = "MAAAMDVDTPSGTNSGAGKKRFEVKKWNAVALWAWDIVVDNCAICRNHIMDLCIECQANQASATSEECTVAWGVCNHAFHFHCISRWLKTRQVCPLDNREWEFQKYGH"

# ---------------------------------------------------------------------------
# Top 12 Protenix candidates — {seed: designed binder sequence}
# Replace PLACEHOLDER_SEQ_* with actual sequences from Protenix outputs.
# ---------------------------------------------------------------------------
CANDIDATES = {
    0: "PLACEHOLDER_SEQ_0",
    4: "PLACEHOLDER_SEQ_4",
    7: "PLACEHOLDER_SEQ_7",
    8: "PLACEHOLDER_SEQ_8",
    9: "PLACEHOLDER_SEQ_9",
    10: "PLACEHOLDER_SEQ_10",
    11: "PLACEHOLDER_SEQ_11",
    12: "PLACEHOLDER_SEQ_12",
    15: "PLACEHOLDER_SEQ_15",
    16: "PLACEHOLDER_SEQ_16",
    17: "PLACEHOLDER_SEQ_17",
    19: "PLACEHOLDER_SEQ_19",
}

BOLTZ2_CSV_HEADER = [
    "seed",
    "boltz2_plddt",
    "boltz2_iptm",
    "boltz2_bt_ipsae",
    "boltz2_tb_ipsae",
    "boltz2_min_ipsae",
]


def write_boltz2_summary(results: list[dict], output_dir: pathlib.Path):
    """Write boltz2_summary.csv from starmap results."""
    csv_path = output_dir / "boltz2_summary.csv"
    rows = []
    for r in results:
        csv_line = r.get("csv_line")
        if csv_line:
            fields = csv_line.split(",")
            rows.append(fields)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(BOLTZ2_CSV_HEADER)
        for row in rows:
            writer.writerow(row)

    print(f"\nSummary written to {csv_path}")
    return csv_path


def print_results_table(results: list[dict]):
    """Print a formatted results table to stdout."""
    print(f"\n{'Seed':>6}  {'pLDDT':>7}  {'ipTM':>7}  "
          f"{'BT-ipSAE':>9}  {'TB-ipSAE':>9}  {'min-ipSAE':>10}  {'Status':>8}")
    print("-" * 72)

    for r in results:
        seed_id = r.get("id", "?")
        if r.get("error"):
            print(f"{seed_id:>6}  {'--':>7}  {'--':>7}  "
                  f"{'--':>9}  {'--':>9}  {'--':>10}  {'FAILED':>8}")
            continue

        csv_line = r.get("csv_line", "")
        if csv_line:
            fields = csv_line.split(",")
            if len(fields) >= 6:
                print(f"{fields[0]:>6}  {fields[1]:>7}  {fields[2]:>7}  "
                      f"{fields[3]:>9}  {fields[4]:>9}  {fields[5]:>10}  {'OK':>8}")
                continue

        print(f"{seed_id:>6}  {'--':>7}  {'--':>7}  "
              f"{'--':>9}  {'--':>9}  {'--':>10}  {'NO DATA':>8}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate RBX1 Protenix candidates with Boltz2 on Vast.ai"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="vast_boltz2_outputs",
        help="Local directory for validation outputs (default: vast_boltz2_outputs)",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from checkpoint if available (default: --resume)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help=f"Max simultaneous Vast.ai instances (default: {config.MAX_CONCURRENT})",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)

    # Convert candidates to {str(seed): sequence} for starmap
    candidates = {str(seed): seq for seed, seq in CANDIDATES.items()}

    print(f"RBX1 Boltz2 Validation — {len(candidates)} candidates")
    print(f"Output dir: {output_dir}")
    print(f"Docker image: {config.DOCKER_IMAGE_BOLTZ2}")
    print(f"Resume: {args.resume}")
    print()

    results = orchestrator.starmap_candidates(
        campaign_id="rbx1-boltz2-validation",
        docker_image=config.DOCKER_IMAGE_BOLTZ2,
        candidates=candidates,
        target_seq=RBX1_TARGET_SEQ,
        output_dir=str(output_dir),
        max_concurrent=args.max_concurrent,
        resume=args.resume,
    )

    write_boltz2_summary(results, output_dir)
    print_results_table(results)

    # Report failures
    failed = [r for r in results if r.get("error")]
    if failed:
        print(f"\n{len(failed)} candidates failed validation.")
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} candidates validated successfully.")


if __name__ == "__main__":
    main()
