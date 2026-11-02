"""5G51 V5-hotspots design runner for a Nebius H100/H200 VM.

Replaces Modal's design_batch.map() fan-out. Runs seed 0 as a gate; only fans
out the remaining seeds if seed 0 produced a valid result. Supports both
single-GPU sequential mode and multi-GPU parallel mode on one VM via
--max-parallel N (each concurrent worker pins to a different GPU index).

Usage:
    python -m nebius.run_campaign --host <VM_IP> --seeds 50
    python -m nebius.run_campaign --host <VM_IP> --seeds 50 --max-parallel 8
    python -m nebius.run_campaign --host <VM_IP> --seeds 50 --resume"""
from __future__ import annotations
import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config, runner as _runner
from .checkpoint import CampaignState

CAMPAIGN_ID = "5g51-v5-hotspots-design"
CSV_HEADER = "seed,sequence,length,cys_count,binder_plddt,target_plddt,iptm"


def _run_one(runner, host, seed, local_out_root, gpu_id):
    """Thin wrapper around runner.run_one_job for thread-pool submission."""
    return runner.run_one_job(
        host=host, image=config.DESIGN_IMAGE, seed=seed,
        config_path=config.DESIGN_CONFIG_PATH, target_cif=config.TARGET_CIF,
        local_out_root=local_out_root, gpu_id=gpu_id,
    )


def run_loop(host, seeds, state, checkpoint_path, local_out_root, runner,
             max_parallel=1):
    """Core loop. Returns True if the seed-0 gate passed (run proceeded), False
    if it blocked. `runner` must expose run_one_job(...) -> dict.

    Concurrency model:
      - The seed-0 gate is ALWAYS sequential (one container, GPU 0). It's the
        cheapest possible way to validate the whole pipeline before fan-out.
      - After the gate, remaining seeds are dispatched concurrently across
        `max_parallel` workers, each pinned to a different GPU index
        (gpu_id = position_in_remaining % max_parallel). State mutations + saves
        are serialized with a Lock so checkpoint writes can't race.
      - max_parallel=1 keeps the original sequential behavior end-to-end.
    """
    local_out_root = Path(local_out_root)
    gate_seed = seeds[0]
    gate_already_done = gate_seed in state.completed_seeds
    state_lock = threading.Lock()

    def _commit_success(seed, result):
        with state_lock:
            state.record_success(seed, result["csv_line"], result["output_dir"])
            state.save(checkpoint_path)
        print(f"[ ok ] seed {seed}: {result['csv_line']}")

    def _commit_failure(seed, err):
        with state_lock:
            state.record_failure(seed, str(err))
            state.save(checkpoint_path)
        print(f"[fail] seed {seed}: {err}", file=sys.stderr)

    # --- Seed-0 gate (always sequential) ---
    if not gate_already_done:
        if gate_seed not in state.completed_seeds:
            print(f"[run ] GATE seed {gate_seed} ...")
            try:
                result = _run_one(runner, host, gate_seed, local_out_root, gpu_id=0)
                _commit_success(gate_seed, result)
            except Exception as e:  # noqa: BLE001
                _commit_failure(gate_seed, e)
                print("[GATE FAILED] seed 0 did not produce a valid result. "
                      "Halting before fan-out. VM left running for debugging.",
                      file=sys.stderr)
                return False

    # --- Fan-out for remaining seeds ---
    remaining = [s for s in seeds if s != gate_seed and s not in state.completed_seeds]
    if not remaining:
        return True

    if max_parallel <= 1:
        # Sequential path — preserves original behavior + tests.
        for seed in remaining:
            print(f"[run ] seed {seed} ...")
            try:
                result = _run_one(runner, host, seed, local_out_root, gpu_id=None)
                _commit_success(seed, result)
            except Exception as e:  # noqa: BLE001
                _commit_failure(seed, e)
        return True

    # Parallel path — ThreadPoolExecutor, one GPU per worker.
    print(f"[fan-out] {len(remaining)} seeds across {max_parallel} GPUs")
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {}
        for i, seed in enumerate(remaining):
            gpu_id = i % max_parallel
            futures[pool.submit(_run_one, runner, host, seed,
                                local_out_root, gpu_id)] = seed
        for fut in as_completed(futures):
            seed = futures[fut]
            try:
                _commit_success(seed, fut.result())
            except Exception as e:  # noqa: BLE001
                _commit_failure(seed, e)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="5G51 V5-hotspots design on Nebius (single- or multi-GPU)")
    parser.add_argument("--host", required=True, help="VM public IP")
    parser.add_argument("--seeds", type=int, default=config.DEFAULT_SEEDS)
    parser.add_argument("--max-parallel", type=int, default=1,
                        help="Concurrent seeds across GPUs on one VM (use 8 for 8xH200)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from existing checkpoint instead of starting fresh")
    args = parser.parse_args(argv)

    seeds = list(range(args.seeds))
    checkpoint_path = config.CHECKPOINTS_DIR / f"{CAMPAIGN_ID}.json"
    local_out_root = config.OUTPUTS_DIR / "5g51_v5_hotspots"

    state = None
    if args.resume:
        state = CampaignState.load(checkpoint_path)
        if state:
            print(f"[resume] {len(state.completed_seeds)} done, "
                  f"{len(state.failed_seeds)} failed")
    if state is None:
        state = CampaignState(campaign_id=CAMPAIGN_ID, image=config.DESIGN_IMAGE,
                              total_seeds=args.seeds)

    ok = run_loop(args.host, seeds, state, checkpoint_path, local_out_root, _runner,
                  max_parallel=args.max_parallel)

    if ok:
        rows = [r["csv_line"] for r in state.results if "csv_line" in r]
        out_csv = local_out_root / "5g51_v5_hotspots_campaign_results.csv"
        _runner.merge_csv(CSV_HEADER, rows, out_csv)
        print(f"\n[done] {len(state.completed_seeds)} ok, "
              f"{len(state.failed_seeds)} failed -> {out_csv}")
        instance_id = config.STATE_DIR / "instance_id"
        if instance_id.exists():
            print(f"\nTeardown the VM when finished:\n"
                  f"  nebius compute instance delete --id {instance_id.read_text().strip()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
