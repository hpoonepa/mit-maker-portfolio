# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein geometry analysis with MDAnalysis."""

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
MDANALYSIS_VERSION = "2.10.0"

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    f"MDAnalysis=={MDANALYSIS_VERSION}",
    "biopython==1.85",
    "numpy==2.2.6",
)
app = modal.App("papercrane-mdanalysis", image=image)


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
        url, headers={"User-Agent": "papercrane-mdanalysis/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        lower_url = str(url).lower()
        suffix = ".cif" if ".cif" in lower_url or ".mmcif" in lower_url else ".pdb"
        return _download(str(url), scratch / f"target{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"target{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "target.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _resolve_reference(merged: dict[str, Any], scratch: Path) -> Path | None:
    url = merged.get("referencePdbUrl")
    if url:
        lower_url = str(url).lower()
        suffix = ".cif" if ".cif" in lower_url or ".mmcif" in lower_url else ".pdb"
        return _download(str(url), scratch / f"reference{suffix}")
    raw = merged.get("referencePdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"reference{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("referencePdb")
    if not ref:
        return None
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "reference.cif",
        )
    raise ValueError("referencePdb must be a 4-character PDB id or local path")


def _prepare(path: Path, scratch: Path, stem: str) -> tuple[Path, bytes]:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBIO, PDBParser

    is_cif = path.suffix.lower() in {".cif", ".mmcif"} or path.read_text(
        errors="ignore"
    ).lstrip().startswith("data_")
    parser = MMCIFParser(QUIET=True) if is_cif else PDBParser(QUIET=True)
    structure = parser.get_structure(stem, str(path))
    pdb_path = scratch / f"{stem}.pdb"
    pdb_writer = PDBIO()
    pdb_writer.set_structure(structure)
    pdb_writer.save(str(pdb_path))
    output = io.StringIO()
    cif_writer = MMCIFIO()
    cif_writer.set_structure(structure)
    cif_writer.save(output)
    return pdb_path, output.getvalue().encode("utf-8")


def _analyze(
    target_path: Path,
    reference_path: Path | None,
    selection: str,
) -> dict[str, float]:
    import MDAnalysis as mda
    import numpy as np
    from MDAnalysis.analysis import rms
    from MDAnalysis.exceptions import NoDataError

    universe = mda.Universe(str(target_path))
    atoms = universe.select_atoms(selection)
    if len(atoms) == 0:
        raise ValueError(f"selection matched no target atoms: {selection}")
    if reference_path is not None:
        reference = mda.Universe(str(reference_path))
        reference_atoms = reference.select_atoms(selection)
        if len(reference_atoms) != len(atoms):
            raise ValueError(
                "target and reference selections must contain the same number of atoms"
            )
        reference.trajectory[0]
        reference_positions = reference_atoms.positions.copy()
    else:
        universe.trajectory[0]
        reference_positions = atoms.positions.copy()

    rmsd_values: list[float] = []
    gyration_values: list[float] = []
    centroids: list[Any] = []
    extents: list[Any] = []
    diagonals: list[float] = []
    for _frame in universe.trajectory:
        positions = atoms.positions.copy()
        rmsd_values.append(
            float(
                rms.rmsd(
                    positions,
                    reference_positions,
                    center=True,
                    superposition=True,
                )
            )
        )
        centroid = positions.mean(axis=0)
        centroids.append(centroid)
        span = np.ptp(positions, axis=0)
        extents.append(span)
        diagonals.append(float(np.linalg.norm(span)))
        try:
            gyration = float(atoms.radius_of_gyration())
        except (AttributeError, NoDataError):
            squared_distances = np.sum((positions - centroid) ** 2, axis=1)
            gyration = float(np.sqrt(np.mean(squared_distances)))
        if not np.isfinite(gyration):
            squared_distances = np.sum((positions - centroid) ** 2, axis=1)
            gyration = float(np.sqrt(np.mean(squared_distances)))
        gyration_values.append(gyration)

    centroid_mean = np.mean(np.asarray(centroids), axis=0)
    extent_max = np.max(np.asarray(extents), axis=0)
    return {
        "frame_count": float(len(rmsd_values)),
        "selected_atom_count": float(len(atoms)),
        "selected_residue_count": float(len(atoms.residues)),
        "rmsd_mean": float(np.mean(rmsd_values)),
        "rmsd_min": float(np.min(rmsd_values)),
        "rmsd_max": float(np.max(rmsd_values)),
        "radius_of_gyration_mean": float(np.mean(gyration_values)),
        "radius_of_gyration_min": float(np.min(gyration_values)),
        "radius_of_gyration_max": float(np.max(gyration_values)),
        "centroid_x": float(centroid_mean[0]),
        "centroid_y": float(centroid_mean[1]),
        "centroid_z": float(centroid_mean[2]),
        "extent_x_max": float(extent_max[0]),
        "extent_y_max": float(extent_max[1]),
        "extent_z_max": float(extent_max[2]),
        "bounding_box_diagonal_mean": float(np.mean(diagonals)),
    }


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/mdanalysis/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-mdanalysis-") as tmp:
            scratch = Path(tmp)
            target_path, content = _prepare(
                _resolve_structure(merged, scratch), scratch, "target"
            )
            reference_source = _resolve_reference(merged, scratch)
            reference_path = (
                _prepare(reference_source, scratch, "reference")[0]
                if reference_source is not None
                else None
            )
            metrics = _analyze(
                target_path,
                reference_path,
                str(merged.get("selection") or "protein and name CA"),
            )
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
                "code": "MDANALYSIS_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "mdanalysis",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "mdanalysis-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
