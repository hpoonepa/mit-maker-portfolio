"""Bounded Modal runner for an independently implemented frozen-model evaluation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

from .runner import BudgetLedger

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879"
CANDIDATE_SHA = "f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c"
PANEL = ("1e7uA04", "1rquA01", "1q16B03", "1d1rA00", "2k4qA00", "2f2cA02", "5k2mA01", "2dp9A01")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_app(timeout_seconds=900):
    import modal
    image = (
        modal.Image.debian_slim(python_version="3.11")
        .pip_install(
            "torch==2.6.0", "pytorch-lightning==2.5.1.post0", "torchmetrics==1.7.0",
            "torchdiffeq==0.2.5", "numpy==1.26.4", "dm-tree==0.1.9",
            "fair-esm==2.0.0", "biopython==1.85", "pandas==2.2.3", "scipy==1.15.2",
        )
        .add_local_dir(ROOT / "artifacts/mars-fm/mars", "/root/mars", copy=True)
        .add_local_dir(ROOT / "senba_sprint", "/root/senba_sprint", copy=True, ignore=["**/__pycache__/**"])
        .add_local_file(ROOT / "artifacts/mars_fm.ckpt", "/weights/source.ckpt", copy=True)
        .add_local_file(ROOT / "artifacts/hf-release/senba.ckpt", "/weights/candidate.ckpt", copy=True)
        .env({"PYTHONPATH": "/root", "OMP_NUM_THREADS": "2"})
    )
    app = modal.App("senba-frozen-evaluation-v1")

    evaluate = app.function(image=image, gpu="H100", cpu=2, memory=16384,
                  timeout=timeout_seconds, startup_timeout=180,
                  max_containers=1, min_containers=0, buffer_containers=0,
                  scaledown_window=2, is_generator=True)(_evaluate)
    return app, evaluate


def _evaluate(payload):
    from senba_sprint.inference import run_pair
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("GPU allocation did not provide CUDA")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    blocks = range(1, 4) if payload.get("extra_k4_blocks", 0) else range(1)
    for block_id in blocks:
        for index, transition in enumerate(payload["transitions"]):
            draw_seed = 20260904 + index + block_id * 1_000_000
            ids = {
                "protein_id": payload["protein_id"],
                "replica_id": str(transition["replica_id"]),
                "start_id": str(transition["start_frame"]),
                "training_seed": "20260825", "inference_seed": str(draw_seed),
            }
            torch.cuda.reset_peak_memory_stats()
            result = run_pair(
                transition["start"], transition["target_ca"], payload["sequence"],
                Path("/weights/source.ckpt"), Path("/weights/candidate.ckpt"),
                SOURCE_SHA, CANDIDATE_SHA, samples=payload["samples"],
                ode_steps=10, seed=draw_seed, ids=ids,
            )
            result["record"]["data_receipt"] = payload["data_receipt"]
            result["record"]["target_frame"] = transition["start_frame"] + 50
            if payload.get("extra_k4_blocks", 0):
                result["record"]["block_id"] = block_id
                result["record"]["provenance"]["augmentation"] = {
                    "block_id": block_id, "generation_seed": draw_seed,
                    "kind": "k4_extension_for_derived_k16",
                }
            result["runtime"]["gpu_name"] = torch.cuda.get_device_name()
            result["runtime"]["torch_version"] = torch.__version__
            result["runtime"]["peak_cuda_memory_bytes"] = torch.cuda.max_memory_allocated()
            yield result


def load_payload(path, samples):
    with np.load(path, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata_json"].item()))
        protein = metadata["protein_id"]
        if protein not in PANEL:
            raise ValueError("protein is outside the prespecified validation panel")
        starts, targets = data["starts"], data["targets_ca"]
        if len(starts) != 20 or len(targets) != 20:
            raise ValueError("five replicas and four starts each are required")
        sequence = str(data["sequence"].item())
        records = metadata["transitions"]
        if len(records) != 20:
            raise ValueError("transition metadata must have 20 entries")
        payload = {
            "protein_id": protein, "sequence": sequence, "samples": samples,
            "data_receipt": {"npz_sha256": sha(path), "metadata": metadata},
            "transitions": [
                {"replica_id": record["replica_id"], "start_frame": record["start_frame"],
                 "start": starts[i].tolist(), "target_ca": targets[i].tolist()}
                for i, record in enumerate(records)
            ],
        }
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--samples", type=int, choices=[4, 16], default=4)
    parser.add_argument("--extra-k4-blocks", type=int, choices=[0, 3], default=0)
    parser.add_argument("--timeout-seconds", type=int, choices=[600, 900], default=None)
    args = parser.parse_args(argv)
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        parser.error("run-id must use only letters, digits, hyphens and underscores")
    if os.environ.get("MODAL_PROFILE") != "senba-sprint":
        parser.error("explicit MODAL_PROFILE=senba-sprint is required")
    if args.extra_k4_blocks and args.samples != 4:
        parser.error("--extra-k4-blocks requires --samples 4")
    if args.extra_k4_blocks and args.timeout_seconds not in (None, 600):
        parser.error("--extra-k4-blocks requires --timeout-seconds 600")
    timeout_seconds = 600 if args.extra_k4_blocks else (args.timeout_seconds or 900)
    payload = load_payload(args.input, args.samples)
    payload["extra_k4_blocks"] = args.extra_k4_blocks
    for path, expected in (
        (ROOT / "artifacts/mars_fm.ckpt", SOURCE_SHA),
        (ROOT / "artifacts/hf-release/senba.ckpt", CANDIDATE_SHA),
    ):
        if sha(path) != expected:
            raise ValueError(f"checkpoint hash mismatch: {path}")
    out = ROOT / "artifacts/runs" / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    # H100 $0.001097/s + two CPUs and 16 GiB memory, <=900 execution
    # seconds, <=180 startup seconds, plus a generous build/idle allowance.
    # Rates checked at https://modal.com/pricing. Invoice is authoritative.
    reservation = 2.0 if timeout_seconds == 600 else 3.0
    ledger = BudgetLedger(ROOT / "artifacts/budget-ledger.json", 30.0, 10.0)
    ledger.reserve(args.run_id, reservation)
    spec = {
        "run_id": args.run_id, "track": "new_frozen_checkpoint_evaluator_v1",
        "reservation_usd": reservation, "timeout_seconds": timeout_seconds,
        "startup_timeout_seconds": 180, "retries": 0, "max_containers": 1,
        "samples": args.samples, "ode_steps": 10, "data_receipt": payload["data_receipt"],
        "extra_k4_blocks": args.extra_k4_blocks,
        "source_sha256": SOURCE_SHA, "candidate_sha256": CANDIDATE_SHA,
        "code_sha256": {p.name: sha(p) for p in sorted((ROOT / "senba_sprint").glob("*.py"))},
        "claim_boundary": "previously_used_validation_panel_new_evaluator_not_exact_reproduction",
    }
    (out / "frozen-spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    started = time.monotonic()
    completed = 0
    try:
        app, evaluate = make_app(timeout_seconds)
        import modal
        with modal.enable_output(), app.run():
            with (out / "records.jsonl").open("x") as records, (out / "runtime.jsonl").open("x") as runtime:
                for result in evaluate.remote_gen(payload):
                    records.write(json.dumps(result["record"], allow_nan=False) + "\n")
                    runtime.write(json.dumps(result["runtime"], allow_nan=False) + "\n")
                    records.flush()
                    runtime.flush()
                    completed += 1
                    print(f"saved transition {completed}/{20 * (3 if args.extra_k4_blocks else 1)}", flush=True)
        (out / "completion.json").write_text(json.dumps({
            "complete": completed == 20 * (3 if args.extra_k4_blocks else 1), "transitions": completed,
            "client_elapsed_seconds": time.monotonic() - started,
            "billing_status": "reservation_held_until_actual_charges_reconciled",
        }, indent=2) + "\n")
        if completed != 20 * (3 if args.extra_k4_blocks else 1):
            raise RuntimeError("remote evaluation ended with missing transitions")
    except BaseException:
        ledger.mark_failed(args.run_id)
        raise
    print(f"RESULTS {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
