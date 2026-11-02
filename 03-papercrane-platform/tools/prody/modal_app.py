# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein normal-mode dynamics analysis with ProDy."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
PRODY_VERSION = "2.6.1"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential")
    .pip_install(
        "numpy==1.26.4", "scipy==1.14.1", "biopython==1.87", f"ProDy=={PRODY_VERSION}"
    )
)
app = modal.App("papercrane-prody", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-prody/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = (
            ".cif"
            if ".cif" in str(url).lower() or ".mmcif" in str(url).lower()
            else ".pdb"
        )
        return _download(str(url), scratch / f"input{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"input{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "input.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _convert(path: Path, scratch: Path) -> tuple[Path, bytes]:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBIO, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    pdb_path = scratch / "input.pdb"
    pdb_writer = PDBIO()
    pdb_writer.set_structure(structure)
    pdb_writer.save(str(pdb_path))
    output = io.StringIO()
    cif_writer = MMCIFIO()
    cif_writer.set_structure(structure)
    cif_writer.save(output)
    return pdb_path, output.getvalue().encode("utf-8")


def _analyse(pdb_path: Path, merged: dict[str, Any]) -> dict[str, float]:
    import numpy as np
    import prody

    atoms = prody.parsePDB(str(pdb_path))
    if atoms is None:
        raise ValueError("ProDy could not parse the supplied structure")
    selection_text = str(merged.get("selection") or "protein and name CA")
    selected = atoms.select(selection_text)
    if selected is None or len(selected) < 4:
        raise ValueError("ProDy selection must contain at least four atoms")
    if len(selected) > 20_000:
        raise ValueError("ProDy selection exceeds the 20,000-atom CPU limit")
    model_name = str(merged.get("model") or "anm").lower()
    cutoff = float(merged.get("cutoff", 15.0))
    requested_modes = int(merged.get("modes", 10))
    if not 4 <= cutoff <= 30 or not 1 <= requested_modes <= 50:
        raise ValueError("cutoff or modes is outside supported bounds")
    if model_name == "anm":
        model = prody.ANM("papercrane")
        model.buildHessian(selected, cutoff=cutoff)
        max_modes = max(1, 3 * len(selected) - 6)
    elif model_name == "gnm":
        model = prody.GNM("papercrane")
        model.buildKirchhoff(selected, cutoff=cutoff)
        max_modes = max(1, len(selected) - 1)
    else:
        raise ValueError(f"unknown ProDy model: {model_name}")
    model.calcModes(n_modes=min(requested_modes, max_modes))
    eigenvalues = np.asarray(model.getEigvals(), dtype=float)
    fluctuations = np.asarray(prody.calcSqFlucts(model), dtype=float)
    collectivities = np.atleast_1d(prody.calcCollectivity(model)).astype(float)
    if eigenvalues.size == 0 or fluctuations.size == 0:
        raise RuntimeError("ProDy did not calculate normal modes")
    return {
        "selected_atom_count": float(len(selected)),
        "mode_count": float(eigenvalues.size),
        "cutoff_angstrom": cutoff,
        "first_eigenvalue": float(eigenvalues[0]),
        "median_eigenvalue": float(np.median(eigenvalues)),
        "last_eigenvalue": float(eigenvalues[-1]),
        "mean_square_fluctuation": float(np.mean(fluctuations)),
        "max_square_fluctuation": float(np.max(fluctuations)),
        "mean_collectivity": float(np.mean(collectivities)),
        "radius_of_gyration": float(prody.calcGyradius(selected)),
    }


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/prody/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(
        str(record["url"]),
        data=content,
        method="PUT",
        headers={"Content-Type": "chemical/x-cif"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=4096)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-prody-") as tmp:
            scratch = Path(tmp)
            pdb_path, content = _convert(_resolve_structure(merged, scratch), scratch)
            metrics = _analyse(pdb_path, merged)
        for seed in seed_values:
            artifact_key = _upload(merged, seed, content)
            _emit(
                {
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "artifactKey": artifact_key,
                    "metrics": metrics,
                }
            )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "PRODY_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "prody",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "prody-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
