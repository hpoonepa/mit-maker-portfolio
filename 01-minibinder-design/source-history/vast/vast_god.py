"""Vast.ai campaign runner for God-tier RBX1 minibinder design.

Replaces modal_god.py — runs design_god.py across multiple seeds on
rented A100-80GB instances via the Vast.ai marketplace.

Usage:
    python -m vast.vast_god                         # single random seed
    python -m vast.vast_god --seed 42               # specific seed
    python -m vast.vast_god --campaign 50            # 50 seeds (0-49)
    python -m vast.vast_god --campaign 50 --resume   # resume interrupted campaign
"""

import argparse
import csv
import pathlib
import random
import time

from . import config
from . import orchestrator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMPAIGN_ID = "god-binder"
DESIGN_SCRIPT = "design_god.py"
DEFAULT_OUTPUT_DIR = "vast_outputs_god"
CSV_HEADER = ["seed", "sequence", "length", "cys_count",
              "binder_plddt", "target_plddt", "iptm"]


# ---------------------------------------------------------------------------
# Single-seed mode
# ---------------------------------------------------------------------------

def run_single(seed: int, output_dir: pathlib.Path):
    """Run one seed on one Vast.ai instance and collect results."""
    print(f"=== GOD BINDER — single seed {seed} ===\n")

    offers = orchestrator.search_offers()
    if not offers:
        raise RuntimeError("No Vast.ai offers found matching GPU/price criteria")
    print(f"Cheapest offer: ${offers[0]['dph_total']:.2f}/hr")

    result = orchestrator.run_single_seed(
        seed=seed,
        docker_image=config.DOCKER_IMAGE_DESIGN,
        offers=offers,
        output_dir=output_dir,
        extra_env={"DESIGN_SCRIPT": DESIGN_SCRIPT},
        onstart_cmd="bash /workspace/entrypoint.sh",
    )

    if "error" in result:
        print(f"\nSeed {seed} FAILED: {result['error']}")
        return

    print(f"\nSeed {seed} complete.")
    if result.get("csv_line"):
        print(f"  CSV: {result['csv_line']}")
    print(f"  Output: {result.get('output_dir', output_dir)}")


# ---------------------------------------------------------------------------
# Campaign mode
# ---------------------------------------------------------------------------

def run_campaign(
    total_seeds: int,
    output_dir: pathlib.Path,
    max_concurrent: int,
    resume: bool,
):
    """Run a multi-seed campaign: one Vast.ai instance per seed."""
    seeds = list(range(total_seeds))

    print("=== GOD BINDER CAMPAIGN ===")
    print(f"Seeds:          {total_seeds}")
    print(f"Max concurrent: {max_concurrent}")
    print(f"Resume:         {resume}")
    print(f"Output:         {output_dir}")
    print(f"Est. cost:      ~${total_seeds * 0.50:.0f} "
          f"(~$1.50/hr x ~20 min/seed)")
    print()

    t0 = time.time()

    results = orchestrator.map_seeds(
        campaign_id=CAMPAIGN_ID,
        docker_image=config.DOCKER_IMAGE_DESIGN,
        seeds=seeds,
        output_dir=str(output_dir),
        extra_env={"DESIGN_SCRIPT": DESIGN_SCRIPT},
        onstart_cmd="bash /workspace/entrypoint.sh",
        max_concurrent=max_concurrent,
        resume=resume,
    )

    elapsed = time.time() - t0

    # Write combined results CSV
    csv_path = output_dir / "god_campaign_results.csv"
    _write_results_csv(results, csv_path)

    # Summary
    n_ok = sum(1 for r in results if "error" not in r)
    n_fail = sum(1 for r in results if "error" in r)
    hours = elapsed / 3600

    print(f"\n=== CAMPAIGN COMPLETE ===")
    print(f"Succeeded: {n_ok}/{total_seeds}")
    print(f"Failed:    {n_fail}/{total_seeds}")
    print(f"Wall time: {elapsed:.0f}s ({hours:.1f}h)")
    print(f"Est. cost: ~${hours * 1.50 * max_concurrent:.1f} "
          f"(~$1.50/hr x {max_concurrent} instances)")
    print(f"Results:   {csv_path}")


def _write_results_csv(results: list[dict], path: pathlib.Path):
    """Write god_campaign_results.csv from collected CSV lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        line = r.get("csv_line")
        if line:
            rows.append(line.strip().split(","))

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow(row)

    print(f"  Wrote {len(rows)} results to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="God-tier binder design campaign on Vast.ai",
    )
    parser.add_argument(
        "--campaign", type=int, default=0,
        help="Total number of seeds to run (campaign mode). Default: 0 (off).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=5,
        help="(Unused — kept for CLI parity with Modal.) Seeds per instance. "
             "On Vast.ai each instance runs one seed.",
    )
    parser.add_argument(
        "--seed", type=int, default=-1,
        help="Run a single seed. -1 = random seed.",
    )
    parser.add_argument(
        "--resume", action="store_true", default=True,
        help="Resume an interrupted campaign from checkpoint.",
    )
    parser.add_argument(
        "--no-resume", dest="resume", action="store_false",
        help="Start a fresh campaign, ignoring any checkpoint.",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=None,
        help=f"Max simultaneous instances. Default: {config.MAX_CONCURRENT}.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"Local directory for outputs. Default: {DEFAULT_OUTPUT_DIR}.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    max_concurrent = args.max_concurrent or config.MAX_CONCURRENT

    if args.campaign > 0:
        run_campaign(
            total_seeds=args.campaign,
            output_dir=output_dir,
            max_concurrent=max_concurrent,
            resume=args.resume,
        )
    else:
        seed = args.seed if args.seed >= 0 else random.randint(0, 999_999)
        run_single(seed, output_dir)


if __name__ == "__main__":
    main()
