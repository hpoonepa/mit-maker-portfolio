"""Vast.ai: RBX1 (2LGV) minibinder design campaign on GPU.

Vast.ai equivalent of modal_2lgv.py — runs the exact same
Protenix2025 + ProteinMPNN + simplex_APGM workflow targeting the
108aa RBX1 construct sequence.

Uses vast.orchestrator.map_seeds() instead of Modal's .map() for
batch binder generation on rented A100-80GB instances.

Usage:
    python -m vast.vast_2lgv                       # 50 seeds (default)
    python -m vast.vast_2lgv --num-seeds 20        # 20 seeds
    python -m vast.vast_2lgv --no-resume           # ignore checkpoint
    python -m vast.vast_2lgv --max-concurrent 5    # limit parallelism

Output format matches modal_2lgv.py for compatibility with filter_rbx1.py.
"""

import argparse
import csv
import pathlib
import sys

from . import config
from . import orchestrator


def main():
    parser = argparse.ArgumentParser(
        description="RBX1 (2LGV) binder design campaign on Vast.ai",
    )
    parser.add_argument(
        "--num-seeds", type=int, default=50,
        help="Number of design seeds to run (default: 50)",
    )
    parser.add_argument(
        "--resume", action="store_true", dest="resume", default=True,
        help="Resume from checkpoint if available (default: True)",
    )
    parser.add_argument(
        "--no-resume", action="store_false", dest="resume",
        help="Ignore existing checkpoint, start fresh",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=None,
        help=f"Max simultaneous instances (default: {config.MAX_CONCURRENT})",
    )
    parser.add_argument(
        "--output-dir", type=str, default="vast_outputs_rbx1",
        help="Local output directory (default: vast_outputs_rbx1)",
    )
    args = parser.parse_args()

    num_seeds = args.num_seeds
    output_dir = pathlib.Path(args.output_dir)

    print("=== RBX1 Construct Binder Design Campaign (Vast.ai) ===")
    print(f"Seeds: {num_seeds}")
    print(f"GPU: {config.GPU_NAME}")
    print(f"Max price: ${config.MAX_PRICE_PER_HOUR:.2f}/hr")
    print(f"Docker image: {config.DOCKER_IMAGE_DESIGN}")
    print(f"Target: RBX1 construct (108aa, sequence-only, no PDB template)")
    print(f"Binder length: 75 residues")
    print(f"Pipeline: Protenix2025 + ProteinMPNN + simplex_APGM")
    print(f"Output: {output_dir}/")
    print(f"Resume: {args.resume}")
    print()

    seeds = list(range(num_seeds))

    results = orchestrator.map_seeds(
        campaign_id="rbx1-design",
        docker_image=config.DOCKER_IMAGE_DESIGN,
        seeds=seeds,
        output_dir=str(output_dir),
        extra_env={"DESIGN_SCRIPT": "design_2lgv.py"},
        onstart_cmd="bash /workspace/entrypoint.sh",
        max_concurrent=args.max_concurrent,
        resume=args.resume,
    )

    # ---- Write campaign_summary.csv in the same format as modal_2lgv.py ----
    csv_path = output_dir / "campaign_summary.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    successes = []
    failures = []

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "sequence", "length", "cys_count",
            "binder_plddt", "target_plddt", "iptm",
        ])
        for res in results:
            if "error" in res:
                failures.append(res["seed"])
                continue
            successes.append(res)
            if res.get("csv_line"):
                writer.writerow(res["csv_line"].split(","))

    # Count any seeds not present in results at all (never started / lost)
    completed_seeds = {r["seed"] for r in results if "error" not in r}
    failed_seeds = {r["seed"] for r in results if "error" in r}

    # ---- Summary ----
    n_ok = len(successes)
    n_fail = len(failures)
    n_total = num_seeds

    print()
    print("=== Campaign Complete ===")
    print(f"Successes: {n_ok}/{n_total}")
    print(f"Failures:  {n_fail}/{n_total}")
    print(f"Summary CSV: {csv_path}")
    print(f"Results: {output_dir}/")

    # Cost estimate based on cheapest offer * job timeout * seeds
    hours_per_seed = config.JOB_TIMEOUT / 3600
    est_cost = n_total * hours_per_seed * config.MAX_PRICE_PER_HOUR
    print(f"Cost estimate: ~${est_cost:.0f} (upper bound, "
          f"{n_total} seeds x {hours_per_seed:.1f}hr x ${config.MAX_PRICE_PER_HOUR:.2f}/hr)")

    # Quality preview
    if successes:
        print()
        print("=== Quality Preview ===")
        for res in successes:
            if res.get("csv_line"):
                parts = res["csv_line"].split(",")
                if len(parts) >= 7:
                    print(f"  seed={parts[0]:>3s}  "
                          f"pLDDT={parts[4]}  ipTM={parts[6]}  cys={parts[3]}")

    # Resume instructions if any failed
    if failed_seeds:
        print()
        print("=== Resume Instructions ===")
        print(f"{len(failed_seeds)} seed(s) failed: {sorted(failed_seeds)}")
        print("Re-run with --resume to retry only the failed seeds:")
        cmd = f"  python -m vast.vast_2lgv --num-seeds {n_total} --resume"
        if args.output_dir != "vast_outputs_rbx1":
            cmd += f" --output-dir {args.output_dir}"
        print(cmd)

    print()
    print("Next: filter candidates with Boltz2 cross-validation")


if __name__ == "__main__":
    main()
