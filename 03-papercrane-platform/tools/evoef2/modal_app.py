# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for EvoEF2 through the open NeuroSnap SDK."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))

image = modal.Image.debian_slim(python_version="3.11").pip_install("neurosnap==2026.6.22")
app = modal.App("papercrane-evoef2", image=image)


def _emit(event: dict[str, Any]) -> None:
    print(json.dumps(event), flush=True)


def _json_arg(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _merged_params(params: Any) -> dict[str, Any]:
    base = _json_arg(params, {}) or {}
    nested = base.get("toolParams")
    return {**base, **(nested if isinstance(nested, dict) else {})}


def _download(url: str, destination: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-evoef2/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"input{suffix}")
    raw = merged.get("targetPdbText") or merged.get("target_pdb_str")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"input{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(f"https://files.rcsb.org/download/{str(ref).upper()}.cif", scratch / "input.cif")
    raise ValueError("targetPdb must be a 4-character PDB id, local path, or uploaded target")


def _load_for_scoring(path: Path, scratch: Path) -> tuple[Any, bytes, list[str]]:
    from neurosnap.io.mmcif import parse_mmcif, save_cif
    from neurosnap.io.pdb import parse_pdb, save_pdb

    if path.suffix.lower() in {".cif", ".mmcif"}:
        structure = parse_mmcif(str(path)).first()
    else:
        structure = parse_pdb(str(path), return_type="ensemble").first()
    pdb_path = scratch / "scoring.pdb"
    cif_path = scratch / "input.cif"
    save_pdb(structure, str(pdb_path))
    save_cif(structure, str(cif_path))
    score_structure = parse_pdb(str(pdb_path), return_type="ensemble").first()
    chains = [str(chain.chain_id) for chain in score_structure.chains()]
    return score_structure, cif_path.read_bytes(), chains


def _flatten(prefix: str, value: Any, output: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten(f"{prefix}_{key}" if prefix else str(key), child, output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output[prefix] = float(value)


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/evoef2/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(str(record["url"]), data=content, method="PUT", headers={"Content-Type": "chemical/x-cif"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=4096)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    from neurosnap.algos.evoef2 import calculate_binding, calculate_stability

    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-evoef2-") as tmp:
            scratch = Path(tmp)
            structure, content, chains = _load_for_scoring(_resolve_structure(merged, scratch), scratch)
            metrics: dict[str, float] = {}
            _flatten("stability", calculate_stability(structure), metrics)
            split1 = [str(x) for x in (merged.get("chainGroup1") or [])]
            split2 = [str(x) for x in (merged.get("chainGroup2") or [])]
            if not split1 and not split2 and len(chains) >= 2:
                split1, split2 = [chains[0]], chains[1:]
            if split1 and split2:
                _flatten("binding", calculate_binding(structure, split1=split1, split2=split2), metrics)
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit({"type": "seed", "seed": seed, "designId": f"{job_id}-{seed}", "artifactKey": artifact_key, "metrics": metrics})
    except Exception as exc:
        _emit({"type": "error", "code": "EVOEF2_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "evoef2", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("evoef2-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"}))
