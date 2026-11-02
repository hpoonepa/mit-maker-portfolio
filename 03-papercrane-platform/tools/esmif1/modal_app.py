# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for Meta's open-source ESM-IF1 model."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

GPU = os.environ.get("GPU", "A10G")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))
CACHE_DIR = "/papercrane-esmif1-cache"
CACHE_VOLUME = modal.Volume.from_name("papercrane-esmif1-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.9")
    .apt_install("build-essential")
    .run_commands(
        "python -m pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.1.2",
        "python -m pip install 'numpy<2' fair-esm==2.0.0 biotite==0.39.0 biopython==1.83 torch-geometric==2.5.3",
    )
    .env({"TORCH_HOME": CACHE_DIR})
)

app = modal.App("papercrane-esmif1", image=image)
_MODEL: Any = None
_ALPHABET: Any = None


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-esmif1/1"})
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


def _as_cif(path: Path) -> bytes:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("input", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _first_chain(path: Path) -> str:
    from Bio.PDB import MMCIFParser, PDBParser

    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("input", str(path))
    chain = next(structure.get_chains(), None)
    if chain is None:
        raise ValueError("input structure contains no chains")
    return str(chain.id)


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/esmif1/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(str(record["url"]), data=content, method="PUT", headers={"Content-Type": "chemical/x-cif"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _model() -> tuple[Any, Any]:
    global _MODEL, _ALPHABET
    if _MODEL is None:
        import esm

        _MODEL, _ALPHABET = esm.pretrained.esm_if1_gvp4_t16_142M_UR50()
        _MODEL = _MODEL.eval().cuda()
    return _MODEL, _ALPHABET


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU, memory=16384, volumes={CACHE_DIR: CACHE_VOLUME})
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    import esm.inverse_folding
    import torch

    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-esmif1-") as tmp:
            input_path = _resolve_structure(merged, Path(tmp))
            chain_id = str(merged.get("chainId") or _first_chain(input_path))
            structure = esm.inverse_folding.util.load_structure(str(input_path), chain_id)
            coords, _native_sequence = esm.inverse_folding.util.extract_coords_from_structure(structure)
            model, alphabet = _model()
            content = _as_cif(input_path)
            temperature = float(merged.get("temperature", 1.0))
            for seed in seed_values:
                torch.manual_seed(seed)
                sampled = model.sample(coords, temperature=temperature)
                ll_full, ll_coord = esm.inverse_folding.util.score_sequence(model, alphabet, coords, sampled)
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": sampled, "artifactKey": artifact_key,
                    "metrics": {"log_likelihood": float(ll_full), "coordinate_log_likelihood": float(ll_coord), "temperature": temperature},
                })
    except Exception as exc:
        _emit({"type": "error", "code": "ESMIF1_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "esmif1", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("esmif1-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"}))
