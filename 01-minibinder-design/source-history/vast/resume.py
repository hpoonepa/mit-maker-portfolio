"""Inspect, resume, and export interrupted Vast.ai campaigns.

Provides CLI tools for managing campaign checkpoints so that partially-
completed runs are never lost.  Checkpoints are JSON files at
config.CHECKPOINT_DIR / "{campaign_id}.json".

Subcommands:
    list           Show all campaigns with progress bars
    show ID        Detailed status of a specific campaign
    resume ID      Re-run a campaign from where it left off
    export ID      Write CSV results from a partial campaign
    retry-failed ID  Re-run only seeds that previously failed

Usage:
    python -m vast.resume list
    python -m vast.resume show rbx1-design
    python -m vast.resume resume rbx1-design
    python -m vast.resume export rbx1-design -o results.csv
    python -m vast.resume retry-failed rbx1-design
"""

import argparse
import csv
import json
import pathlib
import sys
import time

from . import config
from .orchestrator import CampaignState


# ---------------------------------------------------------------------------
# Checkpoint discovery
# ---------------------------------------------------------------------------

def _checkpoint_dir() -> pathlib.Path:
    return config.CHECKPOINT_DIR


def _find_checkpoints() -> list[pathlib.Path]:
    """Return all checkpoint JSON files sorted by modification time (newest first)."""
    ckpt_dir = _checkpoint_dir()
    if not ckpt_dir.exists():
        return []
    files = sorted(ckpt_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _load_checkpoint(campaign_id: str) -> CampaignState:
    """Load a checkpoint by campaign ID, raising a clear error if not found."""
    path = _checkpoint_dir() / f"{campaign_id}.json"
    if not path.exists():
        print(f"Error: No checkpoint found for '{campaign_id}'")
        print(f"  Expected: {path}")
        available = _find_checkpoints()
        if available:
            print(f"  Available campaigns: {', '.join(p.stem for p in available)}")
        sys.exit(1)
    return CampaignState.load(path)


# ---------------------------------------------------------------------------
# Progress bar helper
# ---------------------------------------------------------------------------

def _progress_bar(done: int, total: int, width: int = 30) -> str:
    """Render a simple ASCII progress bar."""
    if total == 0:
        return "[" + "?" * width + "] 0/0"
    frac = done / total
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    pct = frac * 100
    return f"[{bar}] {done}/{total} ({pct:.0f}%)"


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------

def cmd_list(args):
    """Show all campaigns with progress summary."""
    files = _find_checkpoints()
    if not files:
        print("No campaign checkpoints found.")
        print(f"  Checkpoint directory: {_checkpoint_dir()}")
        return

    print(f"{'Campaign':<30s}  {'Progress':<42s}  {'Failed':>6s}  {'Last checkpoint'}")
    print("-" * 110)

    for path in files:
        try:
            state = CampaignState.load(path)
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"{path.stem:<30s}  <corrupt: {exc}>")
            continue

        n_done = len(state.completed_seeds)
        n_fail = len(state.failed_seeds)
        total = state.total_seeds
        bar = _progress_bar(n_done, total)
        last_ckpt = state.last_checkpoint or "?"

        print(f"{state.campaign_id:<30s}  {bar:<42s}  {n_fail:>6d}  {last_ckpt}")


# ---------------------------------------------------------------------------
# Subcommand: show
# ---------------------------------------------------------------------------

def cmd_show(args):
    """Print detailed status of a single campaign."""
    state = _load_checkpoint(args.campaign_id)

    n_done = len(state.completed_seeds)
    n_fail = len(state.failed_seeds)
    n_pending = state.total_seeds - n_done - n_fail

    print(f"Campaign:        {state.campaign_id}")
    print(f"Docker image:    {state.docker_image}")
    print(f"Started:         {state.started_at}")
    print(f"Last checkpoint: {state.last_checkpoint}")
    print()
    print(f"Total seeds:     {state.total_seeds}")
    print(f"Completed:       {n_done}")
    print(f"Failed:          {n_fail}")
    print(f"Pending:         {n_pending}")
    print()
    print(f"Progress: {_progress_bar(n_done, state.total_seeds, width=40)}")

    # Completed seeds
    if state.completed_seeds:
        seeds_str = ", ".join(str(s) for s in sorted(state.completed_seeds)[:50])
        if n_done > 50:
            seeds_str += f" ... (+{n_done - 50} more)"
        print(f"\nCompleted seeds: {seeds_str}")

    # Failed seeds
    if state.failed_seeds:
        seeds_str = ", ".join(str(s) for s in sorted(state.failed_seeds))
        print(f"Failed seeds:    {seeds_str}")

    # Active instances (may be stale)
    if state.active_instances:
        print(f"\nActive instances (possibly stale): {len(state.active_instances)}")
        for inst_id, info in state.active_instances.items():
            print(f"  {inst_id}: {info}")

    # Results preview
    if state.results:
        print(f"\nResults preview (first 5 of {len(state.results)}):")
        for res in state.results[:5]:
            seed = res.get("seed", res.get("id", "?"))
            csv_line = res.get("csv_line", "")
            error = res.get("error", "")
            if error:
                print(f"  seed={seed}: ERROR: {error}")
            elif csv_line:
                parts = csv_line.split(",")
                # Show key metrics if available
                preview = csv_line[:80]
                if len(csv_line) > 80:
                    preview += "..."
                print(f"  seed={seed}: {preview}")
            else:
                print(f"  seed={seed}: (no CSV data)")


# ---------------------------------------------------------------------------
# Subcommand: resume
# ---------------------------------------------------------------------------

_CAMPAIGN_RUNNERS = {
    "rbx1-design": ("vast.vast_2lgv", "main"),
    "5g51-design": ("vast.vast_5g51", "main"),
    "god-binder":  ("vast.vast_god", "main"),
    "god-design":  ("vast.vast_god", "main"),
}


def _detect_runner(campaign_id: str):
    """Return (module_path, function_name) for a campaign, or None."""
    # Exact match
    if campaign_id in _CAMPAIGN_RUNNERS:
        return _CAMPAIGN_RUNNERS[campaign_id]

    # Prefix matching for boltz2 variants
    if campaign_id.startswith("rbx1-boltz2"):
        return ("vast.vast_boltz2", "main")

    # Fallback: check if any known prefix matches
    for prefix in ("rbx1-", "5g51-", "god-"):
        if campaign_id.startswith(prefix):
            # Map prefix to runner
            runner_key = prefix.rstrip("-") + "-design"
            if runner_key in _CAMPAIGN_RUNNERS:
                return _CAMPAIGN_RUNNERS[runner_key]

    return None


def cmd_resume(args):
    """Resume a campaign from its checkpoint."""
    state = _load_checkpoint(args.campaign_id)

    n_done = len(state.completed_seeds)
    n_fail = len(state.failed_seeds)
    n_pending = state.total_seeds - n_done - n_fail

    if n_pending == 0 and n_fail == 0:
        print(f"Campaign '{state.campaign_id}' is already fully complete "
              f"({n_done}/{state.total_seeds} seeds).")
        return

    print(f"Resuming campaign '{state.campaign_id}'")
    print(f"  Completed: {n_done}/{state.total_seeds}")
    print(f"  Failed:    {n_fail}")
    print(f"  Pending:   {n_pending}")
    print()

    runner = _detect_runner(state.campaign_id)
    if runner is None:
        print(f"Error: Cannot detect runner for campaign '{state.campaign_id}'.")
        print("Known campaign types:")
        for key in sorted(_CAMPAIGN_RUNNERS):
            mod, _ = _CAMPAIGN_RUNNERS[key]
            print(f"  {key} -> {mod}")
        print("  rbx1-boltz2* -> vast.vast_boltz2")
        sys.exit(1)

    module_path, func_name = runner
    print(f"Runner: {module_path}.{func_name}()")
    print()

    # Inject --resume into sys.argv so the campaign runner picks it up
    original_argv = sys.argv[:]
    sys.argv = [module_path, "--resume"]

    try:
        import importlib
        mod = importlib.import_module(module_path)
        entry = getattr(mod, func_name)
        entry()
    except SystemExit:
        pass  # argparse may call sys.exit
    finally:
        sys.argv = original_argv


# ---------------------------------------------------------------------------
# Subcommand: export
# ---------------------------------------------------------------------------

def cmd_export(args):
    """Export CSV results from a checkpoint, even if the campaign is incomplete."""
    state = _load_checkpoint(args.campaign_id)

    if not state.results:
        print(f"No results in checkpoint for '{state.campaign_id}'.")
        return

    # Determine output path
    output_path = pathlib.Path(args.output) if args.output else None
    if output_path is None:
        output_path = pathlib.Path(f"{state.campaign_id}_partial_results.csv")

    # Collect CSV lines from results
    rows = []
    for res in state.results:
        csv_line = res.get("csv_line")
        if csv_line:
            rows.append(csv_line.strip().split(","))

    if not rows:
        print(f"No CSV data in {len(state.results)} results for '{state.campaign_id}'.")
        print("Results may not contain csv_line entries yet.")
        return

    # Determine header from the campaign type
    header = _guess_header(state.campaign_id, rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        for row in rows:
            writer.writerow(row)

    n_done = len(state.completed_seeds)
    n_total = state.total_seeds
    print(f"Exported {len(rows)} results ({n_done}/{n_total} seeds completed)")
    print(f"  Output: {output_path}")

    if n_done < n_total:
        n_remaining = n_total - n_done - len(state.failed_seeds)
        print(f"  Note: campaign is incomplete ({n_remaining} pending, "
              f"{len(state.failed_seeds)} failed)")


def _guess_header(campaign_id: str, rows: list[list[str]]) -> list[str]:
    """Guess the CSV header based on campaign type and column count."""
    design_header = ["seed", "sequence", "length", "cys_count",
                     "binder_plddt", "target_plddt", "iptm"]
    boltz2_header = ["candidate", "seed", "sequence", "iptm",
                     "plddt", "rmsd", "pass"]

    if "boltz2" in campaign_id:
        if rows and len(rows[0]) == len(boltz2_header):
            return boltz2_header
    else:
        if rows and len(rows[0]) == len(design_header):
            return design_header

    # Fallback: generic numbered columns
    if rows:
        return [f"col{i}" for i in range(len(rows[0]))]
    return []


# ---------------------------------------------------------------------------
# Subcommand: retry-failed
# ---------------------------------------------------------------------------

def cmd_retry_failed(args):
    """Re-run only the seeds that previously failed."""
    state = _load_checkpoint(args.campaign_id)

    if not state.failed_seeds:
        print(f"No failed seeds in campaign '{state.campaign_id}'.")
        print(f"  Completed: {len(state.completed_seeds)}/{state.total_seeds}")
        return

    failed = sorted(state.failed_seeds)
    print(f"Campaign '{state.campaign_id}' has {len(failed)} failed seeds: {failed}")
    print()

    # Move failed seeds back to pending by clearing them from the failure list
    # The orchestrator will see them as not-completed and re-run them
    ckpt_path = _checkpoint_dir() / f"{state.campaign_id}.json"

    # Create a backup of the current checkpoint
    backup_path = ckpt_path.with_suffix(f".backup-{int(time.time())}.json")
    import shutil
    shutil.copy2(ckpt_path, backup_path)
    print(f"  Checkpoint backup: {backup_path}")

    # Clear the failed list so the orchestrator treats them as pending
    state.failed_seeds = []
    state.last_checkpoint = time.strftime("%Y-%m-%d %H:%M:%S")
    state.save(ckpt_path)
    print(f"  Cleared {len(failed)} failed seeds from checkpoint")
    print()

    # Now resume -- the orchestrator will pick up the formerly-failed seeds
    runner = _detect_runner(state.campaign_id)
    if runner is None:
        print(f"Error: Cannot detect runner for campaign '{state.campaign_id}'.")
        print("Clear the failed seeds manually and use `resume` with the appropriate script.")
        sys.exit(1)

    module_path, func_name = runner
    print(f"Retrying {len(failed)} seeds via {module_path}.{func_name}()")
    print()

    original_argv = sys.argv[:]
    sys.argv = [module_path, "--resume"]

    try:
        import importlib
        mod = importlib.import_module(module_path)
        entry = getattr(mod, func_name)
        entry()
    except SystemExit:
        pass
    finally:
        sys.argv = original_argv


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vast.resume",
        description="Inspect, resume, and export interrupted Vast.ai campaigns.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser(
        "list",
        help="Show all campaigns with progress bars",
    )

    # show
    p_show = sub.add_parser(
        "show",
        help="Detailed status of a specific campaign",
    )
    p_show.add_argument("campaign_id", help="Campaign ID (checkpoint file stem)")

    # resume
    p_resume = sub.add_parser(
        "resume",
        help="Resume a campaign from where it left off",
    )
    p_resume.add_argument("campaign_id", help="Campaign ID to resume")

    # export
    p_export = sub.add_parser(
        "export",
        help="Export CSV results even if campaign is incomplete",
    )
    p_export.add_argument("campaign_id", help="Campaign ID to export")
    p_export.add_argument(
        "-o", "--output",
        help="Output CSV path (default: <campaign_id>_partial_results.csv)",
    )

    # retry-failed
    p_retry = sub.add_parser(
        "retry-failed",
        help="Re-run only seeds that previously failed",
    )
    p_retry.add_argument("campaign_id", help="Campaign ID with failed seeds to retry")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "list": cmd_list,
        "show": cmd_show,
        "resume": cmd_resume,
        "export": cmd_export,
        "retry-failed": cmd_retry_failed,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
