# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Paper Crane Boltz-1x Modal runner.

Uses the maintained Boltz CLI with its explicit ``--model boltz1`` mode while
keeping the same NDJSON/storage contract as the Boltz-2 worker entrypoint.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import modal

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.boltz2.modal_app import (  # noqa: E402
    BOLTZ_VOLUME,
    CACHE_DIR,
    GPU,
    SMOKE_SEQUENCE,
    TIMEOUT_MIN,
    _classify_error,
    _emit_event,
    _emit_yaml,
    _json_arg,
    _numeric_metrics,
    _resolve_cofold,
    _upload_structure,
    image,
)

app = modal.App("boltz1", image=image)


def _predict_impl(
    target_seq: str,
    binder_seq: str | None = None,
    recycling_steps: int = 3,
    sampling_steps: int = 200,
    diffusion_samples: int = 1,
    seed: int = 42,
    use_msa_server: bool = True,
) -> dict:
    import json as py_json
    from subprocess import run

    with TemporaryDirectory() as in_dir, TemporaryDirectory() as out_dir:
        config_path = Path(in_dir) / "in.yaml"
        config_path.write_text(_emit_yaml(target_seq, binder_seq))
        command = [
            "boltz",
            "predict",
            str(config_path),
            "--model",
            "boltz1",
            "--out_dir",
            str(out_dir),
            "--cache",
            CACHE_DIR,
            "--recycling_steps",
            str(recycling_steps),
            "--sampling_steps",
            str(sampling_steps),
            "--diffusion_samples",
            str(diffusion_samples),
            "--seed",
            str(seed),
            "--no_kernels",
        ]
        if use_msa_server:
            command.append("--use_msa_server")
        run(command, check=True)

        structures = sorted(Path(out_dir).rglob("*.cif"))
        if not structures:
            raise RuntimeError(f"Boltz-1 produced no CIFs under {out_dir}")
        structure = structures[0]
        confidence: dict = {}
        confidence_files = sorted(Path(out_dir).rglob("confidence_*.json"))
        if confidence_files:
            raw = py_json.loads(confidence_files[0].read_text())
            confidence = {
                "plddt_mean": float(raw.get("complex_plddt", raw.get("plddt", 0.0))),
                "ptm": float(raw.get("ptm", 0.0)),
                "iptm": float(raw.get("iptm", 0.0)),
                "ipae_mean": float(raw.get("complex_pde", raw.get("pde", 0.0))),
            }
        return {
            "structure_path": str(structure.relative_to(out_dir)),
            "cif_bytes": structure.read_bytes(),
            "confidence": confidence,
        }


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: BOLTZ_VOLUME},
)
def predict(
    target_seq: str,
    binder_seq: str | None = None,
    recycling_steps: int = 3,
    sampling_steps: int = 200,
    diffusion_samples: int = 1,
    seed: int = 42,
    use_msa_server: bool = True,
) -> dict:
    return _predict_impl(
        target_seq,
        binder_seq,
        recycling_steps,
        sampling_steps,
        diffusion_samples,
        seed,
        use_msa_server,
    )


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: BOLTZ_VOLUME},
)
def papercrane_dispatch(job_id: str, seeds, params=None, prev_output=None) -> dict:
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}
    target_seq, binder_seq = _resolve_cofold(merged, params)

    completed = 0
    failed = 0
    for seed in seeds:
        try:
            result = _predict_impl(
                target_seq=str(target_seq),
                binder_seq=str(binder_seq) if binder_seq else None,
                recycling_steps=int(merged.get("recycling_steps", 3)),
                sampling_steps=int(merged.get("sampling_steps", 200)),
                diffusion_samples=int(merged.get("diffusion_samples", 1)),
                seed=int(seed),
                use_msa_server=bool(merged.get("use_msa_server", True)),
            )
            artifact_key = _upload_structure(merged, int(seed), result["cif_bytes"])
            _emit_event({
                "type": "seed",
                "seed": int(seed),
                "artifactKey": artifact_key or f"modal/{job_id}/boltz1/{seed}/{result['structure_path']}",
                "metrics": _numeric_metrics(result.get("confidence") or {}),
            })
            completed += 1
        except Exception as exc:
            code = _classify_error(exc)
            _emit_event({
                "type": "error",
                "seed": int(seed),
                "code": code,
                "message": str(exc)[:500],
                "retryable": code in ("OOM", "TIMEOUT", "INFRA_ERROR"),
            })
            failed += 1

    summary = {"tool": "boltz1", "completed": completed, "failed_seeds": failed}
    _emit_event({"type": "done", "summary": summary, "failed_seeds": failed})
    return summary


@app.local_entrypoint()
def main() -> None:
    result = predict.remote(
        target_seq=SMOKE_SEQUENCE,
        sampling_steps=50,
        diffusion_samples=1,
        seed=42,
    )
    if not result.get("cif_bytes"):
        raise SystemExit("FAIL: Boltz-1 returned no structure")
    print("OK: Boltz-1 structure returned")
