"""
Vast.ai reference script for running a single JAX workload on a rented GPU.

This is the Vast.ai equivalent of modal_run.py. It demonstrates the full
lifecycle: search offers -> rent instance -> run workload -> collect -> destroy.

Vast.ai vs Modal workflow differences:
    Modal:
        - Declarative: define image + function, `modal run` handles the rest.
        - Container is built server-side from your Image spec.
        - Results returned in-process via function return values.
        - Autoscaling and concurrency managed by Modal.

    Vast.ai:
        - Imperative: you search offers, rent instances, SSH in, collect via SCP.
        - You pre-build and push a Docker image to Docker Hub / registry.
        - Results collected by SCP-ing files from /workspace/outputs/.
        - Concurrency managed by the orchestrator's ThreadPoolExecutor.
        - Instances persist until you explicitly destroy them (cost risk!).
        - Incremental checkpointing: results saved after each seed, resumable.

Usage:
    # Run a single seed (default seed=0)
    python -m vast.vast_run

    # Run with a specific seed
    python -m vast.vast_run --seed 42

    # Dry-run: just search offers and print pricing, don't rent anything
    python -m vast.vast_run --dry-run

Prerequisites:
    pip install vastai
    vastai set api-key <YOUR_KEY>
    # Or: export VASTAI_API_KEY=<YOUR_KEY>

    # Build and push your Docker image first:
    docker build -t <user>/mosaic-design:latest -f vast/Dockerfile .
    docker push <user>/mosaic-design:latest
"""

import argparse
import pathlib
import sys

from . import config
from .orchestrator import (
    destroy_all_instances,
    destroy_instance,
    run_single_seed,
    search_offers,
)


def main():
    parser = argparse.ArgumentParser(
        description="Run a single JAX workload on a Vast.ai GPU instance.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for the workload (default: 0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search offers and print pricing without renting anything",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Step 1: Search for GPU offers and print pricing
    # ------------------------------------------------------------------
    print(f"Searching Vast.ai for {config.GPU_NAME} offers "
          f"(max ${config.MAX_PRICE_PER_HOUR:.2f}/hr)...")

    offers = search_offers()
    if not offers:
        print("No offers found matching GPU/price criteria. "
              "Try raising MAX_PRICE_PER_HOUR in vast/config.py.")
        sys.exit(1)

    print(f"\nFound {len(offers)} offers:")
    print(f"  {'Price/hr':>10}  {'GPU':>16}  {'VRAM':>8}  {'Disk':>8}  {'Offer ID':>10}")
    print(f"  {'-'*10}  {'-'*16}  {'-'*8}  {'-'*8}  {'-'*10}")
    for offer in offers[:5]:
        print(f"  ${offer.get('dph_total', 0):>8.2f}  "
              f"{offer.get('gpu_name', '?'):>16}  "
              f"{offer.get('gpu_ram', 0):>6.0f}GB  "
              f"{offer.get('disk_space', 0):>6.0f}GB  "
              f"{offer.get('id', '?'):>10}")

    if args.dry_run:
        print("\n[dry-run] Exiting without renting.")
        return

    # ------------------------------------------------------------------
    # Step 2: Create one instance with a simple JAX test workload
    # ------------------------------------------------------------------
    output_dir = pathlib.Path(config.LOCAL_OUTPUT_DIR / "single_seed_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nLaunching seed {args.seed} on cheapest offer "
          f"(${offers[0]['dph_total']:.2f}/hr)...")
    print(f"Output directory: {output_dir}")

    # ------------------------------------------------------------------
    # Step 3: Wait for completion and collect results
    # ------------------------------------------------------------------
    result = run_single_seed(
        seed=args.seed,
        docker_image=config.DOCKER_IMAGE_DESIGN,
        offers=offers,
        output_dir=output_dir,
        # extra_env={"MY_CUSTOM_VAR": "value"},  # pass extra env vars
    )

    # ------------------------------------------------------------------
    # Step 4: Print results (instance is already destroyed by run_single_seed)
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    if "error" in result:
        print(f"FAILED: {result['error']}")
        sys.exit(1)
    else:
        print(f"Seed {result['seed']}: completed successfully")
        if result.get("csv_line"):
            print(f"  CSV: {result['csv_line']}")
        print(f"  Output: {result.get('output_dir', 'N/A')}")
    print("=" * 60)


# ======================================================================
# EXAMPLES: Common patterns for production campaigns
# ======================================================================
#
# --- Change GPU type ------------------------------------------------
#
#   # In vast/config.py, change GPU_NAME:
#   GPU_NAME = "RTX_4090"       # cheaper, good for ProteinMPNN
#   GPU_NAME = "A100_80GB"      # default, needed for Protenix2025
#   GPU_NAME = "H100_80GB"      # fastest, most expensive
#
#   # Or override per-search:
#   offers = search_offers(gpu_name="RTX_4090", max_price=0.50)
#
#
# --- Parallel execution with map_seeds -----------------------------
#
#   from vast.orchestrator import map_seeds
#
#   results = map_seeds(
#       campaign_id="rbx1-20seed-v2",
#       docker_image=config.DOCKER_IMAGE_DESIGN,
#       seeds=list(range(20)),        # seeds 0-19
#       max_concurrent=5,             # 5 instances at a time
#       extra_env={"RECYCLING": "8"},
#   )
#   # Results are checkpointed after every seed. If interrupted,
#   # re-running with the same campaign_id will resume automatically.
#
#
# --- Validation with starmap_candidates ----------------------------
#
#   from vast.orchestrator import starmap_candidates
#
#   candidates = {
#       "seed_003_rank1": "MKTLLILAVL...",
#       "seed_007_rank1": "MGSSHHHHHH...",
#       "seed_012_rank2": "MKWVTFISLL...",
#   }
#
#   results = starmap_candidates(
#       campaign_id="rbx1-boltz2-validate",
#       docker_image=config.DOCKER_IMAGE_BOLTZ2,
#       candidates=candidates,
#       target_seq="MGSSHHH...",  # target sequence for interface scoring
#       max_concurrent=3,
#   )
#
#
# --- Resume from checkpoint ----------------------------------------
#
#   # map_seeds resumes automatically when called with the same campaign_id.
#   # It reads the checkpoint from vast_checkpoints/<campaign_id>.json
#   # and skips seeds that already completed.
#
#   results = map_seeds(
#       campaign_id="rbx1-20seed-v2",  # same ID -> resumes
#       docker_image=config.DOCKER_IMAGE_DESIGN,
#       seeds=list(range(20)),
#       resume=True,                   # default; set False to start fresh
#   )
#
#   # To force a fresh start, either change the campaign_id or:
#   results = map_seeds(
#       campaign_id="rbx1-20seed-v2",
#       docker_image=config.DOCKER_IMAGE_DESIGN,
#       seeds=list(range(20)),
#       resume=False,                  # discard checkpoint, start over
#   )
#
#
# --- Emergency cleanup ---------------------------------------------
#
#   # If something goes wrong and instances are left running (costs $!):
#   from vast.orchestrator import destroy_all_instances
#   destroy_all_instances()
#
#   # Or from the CLI:
#   vastai destroy instance <ID>
#   vastai show instances  # list all running instances
#


if __name__ == "__main__":
    main()
