"""Utility script for managing Vast.ai instances and campaign state.

Subcommands:
    instances          List all running instances
    destroy-all        Destroy all instances (with confirmation)
    destroy PATTERN    Destroy instances matching a label pattern
    status CAMPAIGN_ID Show checkpoint status for a campaign
    clear CAMPAIGN_ID  Delete checkpoint file to force fresh start
    cost               Estimate total cost of running instances
"""

import argparse
import fnmatch
import sys
from datetime import datetime, timezone

from . import config
from .orchestrator import (
    CampaignState,
    destroy_all_instances,
    destroy_instance,
    list_running_instances,
)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_instances(args):
    """List all running instances with label, GPU, cost, and uptime."""
    instances = list_running_instances()
    if not instances:
        print("No running instances.")
        return

    print(f"{'ID':>8}  {'Label':<24} {'GPU':<16} {'$/hr':>6}  {'Status':<10}  Uptime")
    print("-" * 90)
    now = datetime.now(timezone.utc)
    for inst in instances:
        inst_id = inst.get("id", "?")
        label = inst.get("label", "") or ""
        gpu = inst.get("gpu_name", "?")
        dph = inst.get("dph_total", 0)
        status = inst.get("actual_status", inst.get("status_msg", "?"))

        # Calculate uptime from start_date (epoch seconds)
        start_ts = inst.get("start_date")
        if start_ts:
            try:
                start = datetime.fromtimestamp(float(start_ts), tz=timezone.utc)
                delta = now - start
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes = remainder // 60
                uptime = f"{hours}h {minutes}m"
            except (ValueError, TypeError, OSError):
                uptime = "?"
        else:
            uptime = "?"

        print(f"{inst_id:>8}  {label:<24} {gpu:<16} {dph:>6.2f}  {status:<10}  {uptime}")

    print(f"\nTotal: {len(instances)} instance(s)")


def cmd_destroy_all(args):
    """Destroy all instances after user confirmation."""
    instances = list_running_instances()
    if not instances:
        print("No running instances to destroy.")
        return

    print(f"This will destroy {len(instances)} instance(s):")
    for inst in instances:
        label = inst.get("label", "") or "(no label)"
        print(f"  {inst['id']}  {label}")

    if not args.yes:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    destroy_all_instances()
    print("All instances destroyed.")


def cmd_destroy(args):
    """Destroy instances whose label matches a glob pattern."""
    pattern = args.pattern
    instances = list_running_instances()
    if not instances:
        print("No running instances.")
        return

    matched = [
        inst for inst in instances
        if fnmatch.fnmatch(inst.get("label", "") or "", pattern)
    ]

    if not matched:
        print(f"No instances match pattern '{pattern}'.")
        return

    print(f"Destroying {len(matched)} instance(s) matching '{pattern}':")
    for inst in matched:
        label = inst.get("label", "") or "(no label)"
        try:
            destroy_instance(inst["id"])
            print(f"  {inst['id']}  {label}  -- destroyed")
        except Exception as e:
            print(f"  {inst['id']}  {label}  -- FAILED: {e}")


def cmd_status(args):
    """Show checkpoint status for a campaign."""
    ckpt_path = config.CHECKPOINT_DIR / f"{args.campaign_id}.json"
    if not ckpt_path.exists():
        print(f"No checkpoint found for campaign '{args.campaign_id}'.")
        print(f"  Expected: {ckpt_path}")
        return

    state = CampaignState.load(ckpt_path)
    completed = len(state.completed_seeds)
    failed = len(state.failed_seeds)
    total = state.total_seeds
    remaining = total - completed - failed

    print(f"Campaign: {state.campaign_id}")
    print(f"  Image:          {state.docker_image}")
    print(f"  Started:        {state.started_at}")
    print(f"  Last checkpoint:{state.last_checkpoint}")
    print()
    print(f"  Total seeds:    {total}")
    print(f"  Completed:      {completed}")
    print(f"  Failed:         {failed}")
    print(f"  Remaining:      {remaining}")

    if state.failed_seeds:
        print(f"\n  Failed seeds: {state.failed_seeds}")

    if state.active_instances:
        print(f"\n  Active instances: {list(state.active_instances.keys())}")


def cmd_clear(args):
    """Delete checkpoint file to force a fresh campaign start."""
    ckpt_path = config.CHECKPOINT_DIR / f"{args.campaign_id}.json"
    if not ckpt_path.exists():
        print(f"No checkpoint found for '{args.campaign_id}'.")
        return

    if not args.yes:
        answer = input(
            f"Delete checkpoint for '{args.campaign_id}'? "
            "This cannot be undone. [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    ckpt_path.unlink()
    print(f"Checkpoint deleted: {ckpt_path}")


def cmd_cost(args):
    """Estimate total hourly cost of all running instances."""
    instances = list_running_instances()
    if not instances:
        print("No running instances. Current cost: $0.00/hr")
        return

    total_dph = 0.0
    for inst in instances:
        dph = inst.get("dph_total", 0)
        total_dph += dph

    print(f"Running instances: {len(instances)}")
    print(f"Total cost:        ${total_dph:.2f}/hr")
    print(f"Projected daily:   ${total_dph * 24:.2f}/day")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage Vast.ai instances and campaign state.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # instances
    sub.add_parser("instances", help="List all running instances")

    # destroy-all
    p_da = sub.add_parser("destroy-all", help="Destroy all instances")
    p_da.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # destroy PATTERN
    p_d = sub.add_parser("destroy", help="Destroy instances matching label pattern")
    p_d.add_argument("pattern", help="Glob pattern to match labels (e.g. 'seed-*')")

    # status CAMPAIGN_ID
    p_s = sub.add_parser("status", help="Show campaign checkpoint status")
    p_s.add_argument("campaign_id", help="Campaign identifier")

    # clear CAMPAIGN_ID
    p_c = sub.add_parser("clear", help="Delete checkpoint to force re-run")
    p_c.add_argument("campaign_id", help="Campaign identifier")
    p_c.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # cost
    sub.add_parser("cost", help="Estimate total cost of running instances")

    args = parser.parse_args()

    dispatch = {
        "instances": cmd_instances,
        "destroy-all": cmd_destroy_all,
        "destroy": cmd_destroy,
        "status": cmd_status,
        "clear": cmd_clear,
        "cost": cmd_cost,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
