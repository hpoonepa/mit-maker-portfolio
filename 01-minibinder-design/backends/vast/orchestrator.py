"""Vast.ai orchestrator for mosaic protein design campaigns.

Replaces Modal's .map()/.starmap() with Vast.ai multi-instance management.
Handles: search -> rent -> launch -> monitor -> collect -> destroy.

Key feature: incremental checkpointing — saves results after every seed,
not just when the whole campaign finishes. Resumable from checkpoints.

The instance records and the `vastai` CLI wrapper live in `vastai.py`; this
module is the campaign logic on top of them. `Instance` and `CampaignState` are
re-exported here because that is where callers (`monitor.py`, the per-campaign
`vast_*.py` launchers) have always imported them from."""

import json
import time
import csv
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .vastai import (
    CampaignState,
    Instance,
    _run_vastai,
    create_instance,
    destroy_instance,
    get_instance_info,
    scp_download,
    search_offers,
    ssh_exec,
    wait_for_running,
)

# ---------------------------------------------------------------------------
# Job lifecycle: run one seed on one instance
# ---------------------------------------------------------------------------

def _wait_for_done(instance: Instance, timeout: int = None) -> bool:
    """Poll until /workspace/outputs/DONE exists or timeout."""
    timeout = timeout or config.JOB_TIMEOUT
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = ssh_exec(
                instance,
                "cat /workspace/outputs/DONE 2>/dev/null || echo NOT_DONE",
            )
            if "NOT_DONE" not in out:
                return True
        except Exception:
            pass
        time.sleep(config.POLL_INTERVAL)
    return False


def _collect_seed_results(
    instance: Instance, seed: int, output_dir: pathlib.Path
) -> dict:
    """SCP results from instance and parse CSV line."""
    seed_dir = output_dir / f"seed_{seed:03d}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    try:
        scp_download(instance, "/workspace/outputs/*", str(seed_dir))
    except Exception as e:
        return {"seed": seed, "error": f"SCP failed: {e}"}

    # Parse CSV line
    csv_path = seed_dir / "csv_line.txt"
    csv_line = None
    if csv_path.exists():
        csv_line = csv_path.read_text().strip()

    # Read log
    log_path = seed_dir / "log.txt"
    log = log_path.read_text() if log_path.exists() else ""

    return {"seed": seed, "csv_line": csv_line, "log": log, "output_dir": str(seed_dir)}


def run_single_seed(
    seed: int,
    docker_image: str,
    offers: list[dict],
    output_dir: pathlib.Path,
    extra_env: dict = None,
    onstart_cmd: str = "bash /workspace/entrypoint.sh",
) -> dict:
    """Full lifecycle for one seed: create -> wait -> collect -> destroy."""
    env = {
        "SEED": str(seed),
        "XLA_PYTHON_CLIENT_MEM_FRACTION": config.XLA_MEM_FRACTION,
    }
    if extra_env:
        env.update(extra_env)

    # Rent cheapest available offer
    offer = offers[0]
    instance_id = create_instance(
        offer_id=offer["id"],
        docker_image=docker_image,
        env_vars=env,
        onstart_cmd=onstart_cmd,
        label=f"seed-{seed}",
    )
    print(f"  Seed {seed:3d}: instance {instance_id} (${offer['dph_total']:.2f}/hr)")

    try:
        instance = wait_for_running(instance_id)
        instance.seed = seed
        print(f"  Seed {seed:3d}: running @ {instance.ssh_host}:{instance.ssh_port}")

        done = _wait_for_done(instance)
        if not done:
            print(f"  Seed {seed:3d}: TIMEOUT — collecting partial results")

        result = _collect_seed_results(instance, seed, output_dir)
        return result
    except Exception as e:
        return {"seed": seed, "error": str(e)}
    finally:
        try:
            destroy_instance(instance_id)
            print(f"  Seed {seed:3d}: instance destroyed")
        except Exception:
            print(f"  Seed {seed:3d}: WARNING — could not destroy {instance_id}")


# ---------------------------------------------------------------------------
# map_seeds: replaces Modal .map()
# ---------------------------------------------------------------------------

def map_seeds(
    campaign_id: str,
    docker_image: str,
    seeds: list[int],
    output_dir: str = None,
    extra_env: dict = None,
    onstart_cmd: str = "bash /workspace/entrypoint.sh",
    max_concurrent: int = None,
    resume: bool = True,
) -> list[dict]:
    """
    Launch one Vast.ai instance per seed, collect results incrementally.

    Features:
    - Incremental checkpointing after every completed seed
    - Resume from checkpoint if campaign was interrupted
    - Concurrent instance management via thread pool
    """
    out = pathlib.Path(output_dir or config.LOCAL_OUTPUT_DIR / campaign_id)
    out.mkdir(parents=True, exist_ok=True)
    ckpt_path = config.CHECKPOINT_DIR / f"{campaign_id}.json"
    max_conc = max_concurrent or config.MAX_CONCURRENT

    # Resume from checkpoint if available
    if resume and ckpt_path.exists():
        state = CampaignState.load(ckpt_path)
        remaining = state.pending_seeds(seeds)
        print(f"Resuming campaign '{campaign_id}': "
              f"{len(state.completed_seeds)} done, {len(remaining)} remaining")
    else:
        state = CampaignState(
            campaign_id=campaign_id,
            docker_image=docker_image,
            total_seeds=len(seeds),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        remaining = seeds

    if not remaining:
        print("All seeds already completed!")
        return state.results

    # Search offers once
    offers = search_offers()
    if not offers:
        raise RuntimeError("No Vast.ai offers found matching GPU/price criteria")
    print(f"Found {len(offers)} offers. Cheapest: ${offers[0]['dph_total']:.2f}/hr")
    print(f"Launching {len(remaining)} seeds (max {max_conc} concurrent)...\n")

    def _do_seed(seed):
        result = run_single_seed(
            seed=seed,
            docker_image=docker_image,
            offers=offers,
            output_dir=out,
            extra_env=extra_env,
            onstart_cmd=onstart_cmd,
        )
        # Checkpoint immediately after each seed (thread-safe)
        with state._lock:
            if "error" in result:
                state.failed_seeds.append(seed)
            else:
                state.completed_seeds.append(seed)
                state.results.append(result)
        state.save(ckpt_path)
        return result

    with ThreadPoolExecutor(max_workers=max_conc) as pool:
        futures = {pool.submit(_do_seed, s): s for s in remaining}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"  Seed {seed}: EXCEPTION: {e}")
                with state._lock:
                    state.failed_seeds.append(seed)
                state.save(ckpt_path)

    all_results = list(state.results)

    # Write campaign summary CSV
    _write_summary_csv(all_results, out / "campaign_summary.csv")
    state.save(ckpt_path)

    n_ok = len(state.completed_seeds)
    n_fail = len(state.failed_seeds)
    print(f"\nCampaign '{campaign_id}' complete: {n_ok} succeeded, {n_fail} failed")
    return all_results


# ---------------------------------------------------------------------------
# starmap_candidates: replaces Modal .starmap()
# ---------------------------------------------------------------------------

def starmap_candidates(
    campaign_id: str,
    docker_image: str,
    candidates: dict,
    target_seq: str = "",
    output_dir: str = None,
    extra_env: dict = None,
    onstart_cmd: str = "bash /workspace/entrypoint_boltz2.sh",
    max_concurrent: int = None,
    resume: bool = True,
) -> list[dict]:
    """
    Launch one Vast.ai instance per candidate for validation.
    Replaces Modal's .starmap().
    """
    out = pathlib.Path(output_dir or config.LOCAL_OUTPUT_DIR / campaign_id)
    out.mkdir(parents=True, exist_ok=True)
    ckpt_path = config.CHECKPOINT_DIR / f"{campaign_id}.json"
    max_conc = max_concurrent or config.MAX_CONCURRENT

    items = list(candidates.items()) if isinstance(candidates, dict) else list(candidates)
    all_ids = [cid for cid, _ in items]

    # Resume
    if resume and ckpt_path.exists():
        state = CampaignState.load(ckpt_path)
        done_ids = set(state.completed_seeds)
        remaining = [(cid, seq) for cid, seq in items if cid not in done_ids]
        print(f"Resuming '{campaign_id}': {len(state.completed_seeds)} done, "
              f"{len(remaining)} remaining")
    else:
        state = CampaignState(
            campaign_id=campaign_id,
            docker_image=docker_image,
            total_seeds=len(items),
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        remaining = items

    if not remaining:
        print("All candidates already validated!")
        return state.results

    offers = search_offers()
    if not offers:
        raise RuntimeError("No Vast.ai offers found matching criteria")
    print(f"Found {len(offers)} offers. Cheapest: ${offers[0]['dph_total']:.2f}/hr")
    print(f"Validating {len(remaining)} candidates...\n")

    def _do_candidate(cand_id, sequence):
        seed = abs(hash(cand_id)) % 1000000
        env = {
            "CANDIDATE_ID": str(cand_id),
            "SEED": str(seed),
            "SEQUENCE": sequence,
            "TARGET_SEQ": target_seq,
            "XLA_PYTHON_CLIENT_MEM_FRACTION": config.XLA_MEM_FRACTION,
        }
        if extra_env:
            env.update(extra_env)

        offer = offers[0]
        instance_id = create_instance(
            offer_id=offer["id"],
            docker_image=docker_image,
            env_vars=env,
            onstart_cmd=onstart_cmd,
            label=f"validate-{cand_id}",
        )

        try:
            instance = wait_for_running(instance_id)
            done = _wait_for_done(instance)
            if not done:
                print(f"  {cand_id}: TIMEOUT — collecting partial results")

            cand_dir = out / str(cand_id)
            cand_dir.mkdir(parents=True, exist_ok=True)
            try:
                scp_download(instance, "/workspace/outputs/*", str(cand_dir))
            except Exception as e:
                return {"id": cand_id, "error": f"SCP failed: {e}"}

            csv_path = cand_dir / "csv_line.txt"
            csv_line = csv_path.read_text().strip() if csv_path.exists() else None
            result = {"id": cand_id, "seed": seed, "csv_line": csv_line}

            # Checkpoint (thread-safe)
            with state._lock:
                state.completed_seeds.append(cand_id)
                state.results.append(result)
            state.save(ckpt_path)
            return result
        except Exception as e:
            with state._lock:
                state.failed_seeds.append(cand_id)
            state.save(ckpt_path)
            return {"id": cand_id, "error": str(e)}
        finally:
            try:
                destroy_instance(instance_id)
            except Exception:
                print(f"  {cand_id}: WARNING — could not destroy {instance_id}")

    with ThreadPoolExecutor(max_workers=max_conc) as pool:
        futures = {
            pool.submit(_do_candidate, cid, seq): cid
            for cid, seq in remaining
        }
        for future in as_completed(futures):
            cid = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"  {cid}: EXCEPTION: {e}")
                with state._lock:
                    state.failed_seeds.append(cid)
                state.save(ckpt_path)

    all_results = list(state.results)
    _write_summary_csv(all_results, out / "validation_summary.csv", id_field="id")
    state.save(ckpt_path)
    return all_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_summary_csv(results: list[dict], path: pathlib.Path, id_field: str = "seed"):
    """Write campaign results to summary CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        if r.get("csv_line"):
            row_id = r.get(id_field, "")
            rows.append([row_id] + r["csv_line"].split(","))
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([id_field, "value1", "value2", "value3", "value4", "value5"])
        for row in rows:
            writer.writerow(row)
    print(f"  Summary CSV: {path}")


def list_running_instances() -> list[dict]:
    """List all currently running Vast.ai instances."""
    return _run_vastai(["show", "instances"])


def destroy_all_instances():
    """Emergency cleanup — destroy all running instances."""
    instances = list_running_instances()
    for inst in instances:
        try:
            destroy_instance(inst["id"])
            print(f"Destroyed instance {inst['id']}")
        except Exception as e:
            print(f"Failed to destroy {inst['id']}: {e}")
