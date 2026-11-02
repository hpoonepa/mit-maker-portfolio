# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane CPU structure minimization with PDBFixer and OpenMM."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "openmm==8.5.2",
        "pdbfixer @ git+https://github.com/openmm/pdbfixer.git@94cfa4c",
    )
)

app = modal.App("papercrane-openmm-relax", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-openmm-relax/1"})
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


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/openmm-relax/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(str(record["url"]), data=content, method="PUT", headers={"Content-Type": "chemical/x-cif"})
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


def _minimize(path: Path, merged: dict[str, Any]) -> tuple[bytes, str, dict[str, float]]:
    from openmm import LangevinMiddleIntegrator, Platform, unit
    from openmm.app import ForceField, HBonds, NoCutoff, PDBxFile, Simulation
    from pdbfixer import PDBFixer

    fixer = PDBFixer(filename=str(path))
    atoms_before = sum(1 for _ in fixer.topology.atoms())
    fixer.findMissingResidues()
    if not bool(merged.get("addMissingResidues", True)):
        fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(float(merged.get("ph", 7.0)))

    forcefield = ForceField("amber14-all.xml", "implicit/gbn2.xml")
    system = forcefield.createSystem(fixer.topology, nonbondedMethod=NoCutoff, constraints=HBonds)
    integrator = LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
    platform = Platform.getPlatformByName("CPU")
    simulation = Simulation(fixer.topology, system, integrator, platform)
    simulation.context.setPositions(fixer.positions)
    initial = simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    tolerance = float(merged.get("toleranceKjMol", 10.0)) * unit.kilojoules_per_mole / unit.nanometer
    simulation.minimizeEnergy(tolerance=tolerance, maxIterations=int(merged.get("maxIterations", 500)))
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    final = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    output = io.StringIO()
    PDBxFile.writeFile(fixer.topology, state.getPositions(), output, keepIds=True)
    metrics = {
        "initial_energy_kj_mol": float(initial),
        "final_energy_kj_mol": float(final),
        "energy_change_kj_mol": float(final - initial),
        "atoms_before": float(atoms_before),
        "atoms_after": float(sum(1 for _ in fixer.topology.atoms())),
    }
    return output.getvalue().encode("utf-8"), _sequence(fixer.topology), metrics


@app.function(timeout=TIMEOUT_MIN * 60, cpu=4.0, memory=8192)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-openmm-relax-") as tmp:
            content, sequence, metrics = _minimize(_resolve_structure(merged, Path(tmp)), merged)
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": sequence or None, "artifactKey": artifact_key, "metrics": metrics,
                })
    except Exception as exc:
        _emit({"type": "error", "code": "OPENMM_RELAX_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "openmm-relax", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("openmm-relax-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"}))
