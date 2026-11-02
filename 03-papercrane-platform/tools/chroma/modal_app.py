# /// script
# requires-python = ">=3.10"
# dependencies = ["modal>=1.0"]
# ///
"""Paper Crane Chroma 1.0 Modal runner.

The official Chroma package requires a Generate Biomedicines access token for
its public checkpoints. Supply ``CHROMA_API_KEY`` through a Modal secret and
set ``CHROMA_MODAL_SECRET`` to that secret's name before starting the worker.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import modal

GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 60))
CHROMA_VOLUME_NAME = "papercrane-chroma-cache"
CHROMA_CACHE = modal.Volume.from_name(CHROMA_VOLUME_NAME, create_if_missing=True)
CHROMA_CACHE_DIR = f"/{CHROMA_VOLUME_NAME}"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "build-essential")
    .pip_install("generate-chroma==1.0.0", "torch==2.1.2", "numpy<2")
)
app = modal.App("chroma", image=image)

secret_name = os.environ.get("CHROMA_MODAL_SECRET")
secrets = [modal.Secret.from_name(secret_name)] if secret_name else []


def _json_arg(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _emit_event(event: dict) -> None:
    print(json.dumps(event), flush=True)


def _register_access_token() -> None:
    token = os.environ.get("CHROMA_API_KEY")
    if not token:
        raise RuntimeError(
            "Chroma requires CHROMA_API_KEY. Add it to a Modal secret and set CHROMA_MODAL_SECRET."
        )
    from chroma.utility.api import register_key

    register_key(token)


def _upload_structure(merged: dict, seed: int, content: bytes) -> str | None:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict):
        return None

    import urllib.request

    request = urllib.request.Request(
        str(record["url"]),
        data=content,
        method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _sample_impl(length: int, steps: int, temperature: float, seed: int) -> dict:
    import torch
    from chroma import Chroma

    _register_access_token()
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    model = Chroma(device="cuda" if torch.cuda.is_available() else "cpu")
    protein = model.sample(
        samples=1,
        steps=steps,
        chain_lengths=[length],
        temperature_S=max(0.001, temperature),
    )
    with TemporaryDirectory() as output_dir:
        output_path = Path(output_dir) / "design.cif"
        protein.to(str(output_path))
        content = output_path.read_bytes()
    return {"cif_bytes": content, "metrics": {"length": float(length)}}


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CHROMA_CACHE_DIR: CHROMA_CACHE},
    secrets=secrets,
)
def predict(length: int = 100, steps: int = 500, temperature: float = 1.0, seed: int = 42):
    return _sample_impl(length, steps, temperature, seed)


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CHROMA_CACHE_DIR: CHROMA_CACHE},
    secrets=secrets,
)
def papercrane_dispatch(job_id: str, seeds, params=None, prev_output=None) -> dict:
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}
    length = int(merged.get("length", 100))
    steps = int(merged.get("steps", 500))
    temperature = float(merged.get("temperature", 1.0))

    completed = 0
    failed = 0
    for seed in seeds:
        try:
            result = _sample_impl(length, steps, temperature, int(seed))
            artifact_key = _upload_structure(merged, int(seed), result["cif_bytes"])
            _emit_event({
                "type": "seed",
                "seed": int(seed),
                "artifactKey": artifact_key or f"modal/{job_id}/chroma/{seed}/design.cif",
                "metrics": result["metrics"],
            })
            completed += 1
        except Exception as exc:
            _emit_event({
                "type": "error",
                "seed": int(seed),
                "code": "RUNTIME_ERROR",
                "message": str(exc)[:500],
                "retryable": False,
            })
            failed += 1

    summary = {"tool": "chroma", "completed": completed, "failed_seeds": failed}
    _emit_event({"type": "done", "summary": summary, "failed_seeds": failed})
    return summary


@app.local_entrypoint()
def main() -> None:
    result = predict.remote(length=50, steps=50, temperature=1.0, seed=42)
    if not result.get("cif_bytes"):
        raise SystemExit("FAIL: Chroma returned no structure")
    print("OK: Chroma structure returned")
