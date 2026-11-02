"""Live monitoring dashboard for running Vast.ai campaigns.

Prints a refreshing terminal view showing instance status, campaign progress,
latest results, cost estimates, and ETA. Auto-refreshes every N seconds."""

import argparse
import os
import pathlib
import time

from . import config
from .orchestrator import CampaignState, list_running_instances


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _clear_screen():
    os.system("clear")


def _progress_bar(done: int, total: int, width: int = 40) -> str:
    """Render a text progress bar: [####----] 15/50 (30%)"""
    if total == 0:
        return "[" + "-" * width + "] 0/0 (0%)"
    frac = done / total
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    pct = frac * 100
    return f"[{bar}] {done}/{total} ({pct:.0f}%)"


def _format_elapsed(seconds: float) -> str:
    """Format seconds into HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_started_at(started_at: str) -> float:
    """Parse CampaignState.started_at into a Unix timestamp."""
    try:
        return time.mktime(time.strptime(started_at, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return time.time()


# ---------------------------------------------------------------------------
# Dashboard sections
# ---------------------------------------------------------------------------

def _print_header(state: CampaignState, elapsed_s: float):
    print("=" * 72)
    print(f"  MOSAIC Campaign Monitor  --  {state.campaign_id}")
    print("=" * 72)
    print(f"  Image:    {state.docker_image}")
    print(f"  Started:  {state.started_at}")
    print(f"  Elapsed:  {_format_elapsed(elapsed_s)}")
    print()


def _print_progress(state: CampaignState):
    done = len(state.completed_seeds)
    failed = len(state.failed_seeds)
    total = state.total_seeds
    bar = _progress_bar(done + failed, total)

    print(f"  Progress:  {bar}")
    print(f"  Completed: {done}   Failed: {failed}   Remaining: {total - done - failed}")
    print()


def _print_instances_table(instances: list[dict]):
    print("-" * 72)
    print("  RUNNING INSTANCES")
    print("-" * 72)

    if not instances:
        print("  (none)")
        print()
        return

    # Header
    print(f"  {'ID':>8}  {'Label':<20}  {'Status':<12}  {'GPU':<16}  {'$/hr':>6}")
    print(f"  {'--------':>8}  {'--------------------':<20}  {'------------':<12}  {'----------------':<16}  {'------':>6}")

    for inst in instances:
        inst_id = inst.get("id", "?")
        label = inst.get("label", "-") or "-"
        status = inst.get("actual_status", inst.get("status_msg", "unknown"))
        gpu = inst.get("gpu_name", "?")
        dph = inst.get("dph_total", 0)
        print(f"  {inst_id:>8}  {label:<20}  {status:<12}  {gpu:<16}  ${dph:>5.2f}")

    print()


def _print_latest_results(state: CampaignState, n: int = 5):
    print("-" * 72)
    print(f"  LATEST RESULTS (last {n})")
    print("-" * 72)

    if not state.results:
        print("  (no results yet)")
        print()
        return

    recent = state.results[-n:]
    for r in recent:
        seed = r.get("seed", r.get("id", "?"))
        csv_line = r.get("csv_line", None)
        if csv_line:
            # Truncate long CSV lines for display
            display = csv_line if len(csv_line) <= 60 else csv_line[:57] + "..."
            print(f"  seed {seed:>5}:  {display}")
        else:
            print(f"  seed {seed:>5}:  (no CSV output)")

    print()


def _print_cost_estimate(state: CampaignState, instances: list[dict], elapsed_s: float):
    print("-" * 72)
    print("  COST & ETA")
    print("-" * 72)

    elapsed_h = elapsed_s / 3600.0
    total_dph = sum(inst.get("dph_total", 0) for inst in instances)
    n_instances = len(instances)

    # Approximate cost: hours * total $/hr across active instances
    # This is a rough estimate; actual billing may differ.
    est_cost = elapsed_h * total_dph if total_dph > 0 else 0

    print(f"  Active instances:  {n_instances}")
    print(f"  Combined rate:     ${total_dph:.2f}/hr")
    print(f"  Est. cost so far:  ${est_cost:.2f}")

    # ETA based on average completion time per seed
    done = len(state.completed_seeds) + len(state.failed_seeds)
    remaining = state.total_seeds - done

    if done > 0 and remaining > 0:
        avg_per_seed = elapsed_s / done
        # With concurrent instances, throughput scales
        concurrent = max(n_instances, 1)
        eta_s = (remaining / concurrent) * avg_per_seed
        est_total_cost = est_cost + (eta_s / 3600.0) * total_dph
        print(f"  Avg time/seed:     {_format_elapsed(avg_per_seed)}")
        print(f"  ETA remaining:     {_format_elapsed(eta_s)}")
        print(f"  Est. total cost:   ${est_total_cost:.2f}")
    elif remaining == 0:
        print("  All seeds finished.")
    else:
        print("  ETA:               (waiting for first completion)")

    print()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _render_dashboard(campaign_id: str):
    """Render one frame of the dashboard. Returns False if checkpoint missing."""
    ckpt_path = config.CHECKPOINT_DIR / f"{campaign_id}.json"

    if not ckpt_path.exists():
        print(f"No checkpoint found for campaign '{campaign_id}'")
        print(f"  Expected: {ckpt_path}")
        print()
        print("Is the campaign running? Start it first, then monitor.")
        return False

    state = CampaignState.load(ckpt_path)
    started_ts = _parse_started_at(state.started_at)
    elapsed_s = time.time() - started_ts

    # Fetch running instances (may fail if vastai CLI unavailable)
    try:
        instances = list_running_instances()
    except Exception:
        instances = []

    _clear_screen()
    _print_header(state, elapsed_s)
    _print_progress(state)
    _print_instances_table(instances)
    _print_latest_results(state)
    _print_cost_estimate(state, instances, elapsed_s)

    now = time.strftime("%H:%M:%S")
    print(f"  Last refresh: {now}    (Ctrl+C to exit)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Live monitoring dashboard for Vast.ai campaigns"
    )
    parser.add_argument(
        "--campaign",
        required=True,
        help="Campaign ID to monitor (matches checkpoint filename)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Refresh interval in seconds (default: 30)",
    )
    args = parser.parse_args()

    print(f"Monitoring campaign '{args.campaign}' (refresh every {args.interval}s)")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            ok = _render_dashboard(args.campaign)
            if not ok:
                # No checkpoint yet — wait and retry
                pass
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


if __name__ == "__main__":
    main()
