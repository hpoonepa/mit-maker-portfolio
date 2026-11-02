# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein-protein binding affinity prediction with PRODIGY."""

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
PRODIGY_VERSION = "2.4.0"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential")
    .pip_install(f"prodigy-prot=={PRODIGY_VERSION}", "biopython==1.87")
)
app = modal.App("papercrane-prodigy", image=image)


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
    request = urllib.request.Request(
        url, headers={"User-Agent": "papercrane-prodigy/1"}
    )
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
    ref = merged.get("targetPdb") or "1BRS"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "input.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded complex"
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


def _predict(pdb_path: Path, merged: dict[str, Any]) -> dict[str, float]:
    from prodigy_prot.modules.parsers import parse_structure
    from prodigy_prot.modules.prodigy import Prodigy

    models, chain_count, _ = parse_structure(str(pdb_path))
    if not models:
        raise ValueError("PRODIGY could not parse a model from the structure")
    model = models[0]
    selection_value = merged.get("selection")
    selection = None
    if selection_value is not None:
        if not isinstance(selection_value, list) or len(selection_value) < 2:
            raise ValueError(
                "selection must contain at least two disjoint chain groups"
            )
        selection = [str(group).strip() for group in selection_value]
        if any(not group for group in selection):
            raise ValueError("PRODIGY chain groups must not be empty")
    elif chain_count < 2:
        raise ValueError(
            "PRODIGY requires an assembled complex with at least two protein chains"
        )
    temperature = float(merged.get("temperature", 25.0))
    distance_cutoff = float(merged.get("distanceCutoff", 5.5))
    accessibility_threshold = float(merged.get("accessibilityThreshold", 0.05))
    if not 0 <= temperature <= 100 or not 3 <= distance_cutoff <= 10:
        raise ValueError("temperature or distanceCutoff is outside supported bounds")
    if not 0 <= accessibility_threshold <= 1:
        raise ValueError("accessibilityThreshold must be between zero and one")
    predictor = Prodigy(
        model=model, name="papercrane", selection=selection, temp=temperature
    )
    predictor.predict(
        distance_cutoff=distance_cutoff, acc_threshold=accessibility_threshold
    )
    result = predictor.as_dict()
    metrics = {
        "binding_affinity_kcal_mol": float(result["ba_val"]),
        "dissociation_constant_m": float(result["kd_val"]),
        "intermolecular_contacts": float(result["ICs"]),
        "nis_apolar_percent": float(result["nis_a"]),
        "nis_charged_percent": float(result["nis_c"]),
        "nis_polar_percent": max(
            0.0, 100.0 - float(result["nis_a"]) - float(result["nis_c"])
        ),
        "chain_count": float(chain_count),
        "temperature_celsius": temperature,
    }
    for code in ("CC", "CP", "AC", "PP", "AP", "AA"):
        metrics[f"contacts_{code.lower()}"] = float(result[code])
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/prodigy/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-prodigy-") as tmp:
            scratch = Path(tmp)
            pdb_path, content = _convert(_resolve_structure(merged, scratch), scratch)
            metrics = _predict(pdb_path, merged)
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
                "code": "PRODIGY_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "prodigy",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "prodigy-smoke", json.dumps([0]), json.dumps({"targetPdb": "1BRS"})
    )
