# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""OpenMM PDBFixer 1.12 Modal adapter for Papercrane."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "openmm==8.5.2",
        "pdbfixer @ git+https://github.com/openmm/pdbfixer.git@94cfa4c",
    )
)

app = modal.App("papercrane-pdbfixer", image=image)


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
    tool_params = base.get("toolParams")
    return {**base, **(tool_params if isinstance(tool_params, dict) else {})}


def _download(url: str, destination: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-pdbfixer/1"})
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
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / f"{str(ref).lower()}.cif",
        )
    raise ValueError("targetPdb must be a 4-character PDB id, local path, or uploaded target")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/pdbfixer/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(
        str(record["url"]),
        data=content,
        method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _sequence(topology: Any) -> str:
    aa3 = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    return "".join(aa3.get(residue.name.upper(), "") for residue in topology.residues())


def _fix(input_path: Path, merged: dict[str, Any]) -> tuple[bytes, str, dict[str, float]]:
    from openmm.app import PDBxFile
    from pdbfixer import PDBFixer

    fixer = PDBFixer(filename=str(input_path))
    atoms_before = sum(1 for _ in fixer.topology.atoms())
    residues_before = sum(1 for _ in fixer.topology.residues())

    fixer.findMissingResidues()
    missing_residues = float(sum(len(names) for names in fixer.missingResidues.values()))
    if not bool(merged.get("addMissingResidues", True)):
        fixer.missingResidues = {}

    fixer.findNonstandardResidues()
    nonstandard = float(len(fixer.nonstandardResidues))
    if bool(merged.get("replaceNonstandardResidues", True)):
        fixer.replaceNonstandardResidues()

    if bool(merged.get("removeHeterogens", False)):
        fixer.removeHeterogens(keepWater=bool(merged.get("keepWater", True)))

    fixer.findMissingAtoms()
    missing_atoms = float(
        sum(len(atoms) for atoms in fixer.missingAtoms.values())
        + sum(len(atoms) for atoms in fixer.missingTerminals.values())
    )
    fixer.addMissingAtoms()
    if bool(merged.get("addHydrogens", True)):
        fixer.addMissingHydrogens(float(merged.get("ph", 7.0)))

    atoms_after = sum(1 for _ in fixer.topology.atoms())
    residues_after = sum(1 for _ in fixer.topology.residues())
    output = io.StringIO()
    PDBxFile.writeFile(fixer.topology, fixer.positions, output, keepIds=True)
    metrics = {
        "atoms_before": float(atoms_before),
        "atoms_after": float(atoms_after),
        "atoms_added": float(atoms_after - atoms_before),
        "residues_before": float(residues_before),
        "residues_after": float(residues_after),
        "missing_residues_detected": missing_residues,
        "missing_atoms_detected": missing_atoms,
        "nonstandard_residues_detected": nonstandard,
    }
    return output.getvalue().encode("utf-8"), _sequence(fixer.topology), metrics


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=4096)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-pdbfixer-") as tmp:
            input_path = _resolve_structure(merged, Path(tmp))
            content, sequence, metrics = _fix(input_path, merged)
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "sequence": sequence or None,
                    "artifactKey": artifact_key,
                    "metrics": metrics,
                })
    except Exception as exc:
        _emit({"type": "error", "code": "PDBFIXER_FAILED", "message": str(exc), "retryable": False})
        raise

    summary = {"tool": "pdbfixer", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("pdbfixer-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"}))
