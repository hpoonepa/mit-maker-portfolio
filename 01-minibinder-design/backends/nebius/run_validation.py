"""Validate the 5G51 V4 sequences on one Nebius GPU instance.

Entrypoint contract: entrypoint_boltz2.sh reads SEED + SEQUENCE + optional
TARGET_SEQ env vars directly (not DESIGN_SCRIPT/EXTRA_ARGS). run_loop is the
single production path: it calls runner.run_validation_job, which sets those
env vars so the container runs validate_boltz2.py SEED SEQUENCE 5G51.cif.

Usage:
    python -m nebius.run_validation --host <VM_IP>
    python -m nebius.run_validation --host <VM_IP> --resume"""
from __future__ import annotations
import argparse
import sys

from . import config, runner as _runner
from minibinder.prepare.candidates_5g51 import CANDIDATES
from .checkpoint import CampaignState

CAMPAIGN_ID = "5g51-v4-boltz2"
CSV_HEADER = "seed,boltz2_plddt,boltz2_iptm,boltz2_bt_ipsae,boltz2_tb_ipsae,boltz2_min_ipsae"


def run_loop(host, candidates, state, checkpoint_path, local_out_root, runner):
    """Sequential loop over (seed, sequence) candidates. Records failures, continues."""
    for seed, sequence in candidates:
        if seed in state.completed_seeds:
            print(f"[skip] candidate {seed} already completed")
            continue
        print(f"[run ] candidate {seed} ...")
        try:
            result = runner.run_validation_job(
                host=host, image=config.BOLTZ2_IMAGE, seed=seed,
                sequence=sequence, candidate_id=f"seed_{seed:03d}",
                local_out_root=local_out_root,
            )
            state.record_success(seed, result["csv_line"], result["output_dir"])
            state.save(checkpoint_path)
            print(f"[ ok ] candidate {seed}: {result['csv_line']}")
        except Exception as e:  # noqa: BLE001
            state.record_failure(seed, str(e))
            state.save(checkpoint_path)
            print(f"[fail] candidate {seed}: {e}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sequential Boltz2 validation on Nebius")
    parser.add_argument("--host", required=True, help="VM public IP")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    checkpoint_path = config.CHECKPOINTS_DIR / f"{CAMPAIGN_ID}.json"
    local_out_root = config.OUTPUTS_DIR / "boltz2_5g51_v4"

    state = None
    if args.resume:
        state = CampaignState.load(checkpoint_path)
    if state is None:
        state = CampaignState(campaign_id=CAMPAIGN_ID, image=config.BOLTZ2_IMAGE,
                              total_seeds=len(CANDIDATES))

    run_loop(args.host, CANDIDATES, state, checkpoint_path, local_out_root, _runner)

    rows = [r["csv_line"] for r in state.results if "csv_line" in r]
    out_csv = local_out_root / "boltz2_5g51_v4_results.csv"
    _runner.merge_csv(CSV_HEADER, rows, out_csv)
    print(f"\n[done] {len(state.completed_seeds)} ok, "
          f"{len(state.failed_seeds)} failed -> {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
