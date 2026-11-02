# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane structure preparation with PDB2PQR."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "pdb2pqr==3.7.1",
    "propka==3.5.1",
    "biopython==1.85",
)
app = modal.App("papercrane-pdb2pqr", image=image)


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
        url, headers={"User-Agent": "papercrane-pdb2pqr/1"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"source{suffix}")
    raw = merged.get("targetPdbText") or merged.get("target_pdb_str")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"source{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.pdb",
            scratch / "source.pdb",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _as_pdb(path: Path, destination: Path) -> Path:
    from Bio.PDB import PDBIO, MMCIFParser, PDBParser, Select

    class FirstModel(Select):
        def accept_model(self, model: Any) -> bool:
            return bool(model.id == 0)

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(str(destination), select=FirstModel())
    return destination


def _pdb_as_cif(path: Path) -> tuple[bytes, str]:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("prepared", str(path))
    model = next(structure.get_models())
    aa3 = {
        "ALA": "A",
        "ARG": "R",
        "ASN": "N",
        "ASP": "D",
        "CYS": "C",
        "GLN": "Q",
        "GLU": "E",
        "GLY": "G",
        "HIS": "H",
        "ILE": "I",
        "LEU": "L",
        "LYS": "K",
        "MET": "M",
        "PHE": "F",
        "PRO": "P",
        "SER": "S",
        "THR": "T",
        "TRP": "W",
        "TYR": "Y",
        "VAL": "V",
    }
    sequence = "".join(
        aa3.get(residue.resname.upper(), "")
        for residue in model.get_residues()
        if residue.id[0] == " "
    )
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8"), sequence


def _atom_summary(pqr_path: Path) -> dict[str, float]:
    atoms = [
        line
        for line in pqr_path.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    if not atoms:
        raise RuntimeError("PDB2PQR produced no atoms")
    charges = [float(line.split()[-2]) for line in atoms]
    radii = [float(line.split()[-1]) for line in atoms]
    hydrogens = sum(
        1
        for line in atoms
        if line.split()[2].lstrip("0123456789").upper().startswith("H")
    )
    return {
        "atom_count": float(len(atoms)),
        "hydrogen_count": float(hydrogens),
        "net_charge": float(sum(charges)),
        "mean_atomic_radius": float(sum(radii) / len(radii)),
        "min_atomic_radius": float(min(radii)),
        "max_atomic_radius": float(max(radii)),
    }


def _prepare(
    path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[bytes, str, dict[str, float]]:
    input_pdb = _as_pdb(path, scratch / "input.pdb")
    prepared_pdb = scratch / "prepared.pdb"
    prepared_pqr = scratch / "prepared.pqr"
    command = [
        "pdb2pqr",
        "--ff",
        str(merged.get("forceField") or "AMBER").upper(),
        "--titration-state-method",
        "propka",
        "--with-ph",
        str(float(merged.get("ph", 7.0))),
        "--pdb-output",
        str(prepared_pdb),
    ]
    if bool(merged.get("keepChain", True)):
        command.append("--keep-chain")
    if bool(merged.get("dropWater", False)):
        command.append("--drop-water")
    command.extend([str(input_pdb), str(prepared_pqr)])
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"PDB2PQR exited with {completed.returncode}: {detail}")
    if not prepared_pdb.is_file() or not prepared_pqr.is_file():
        raise RuntimeError("PDB2PQR did not produce prepared PDB and PQR files")
    content, sequence = _pdb_as_cif(prepared_pdb)
    metrics = _atom_summary(prepared_pqr)
    metrics["ph"] = float(merged.get("ph", 7.0))
    return content, sequence, metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/pdb2pqr/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=4096)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-pdb2pqr-") as tmp:
            scratch = Path(tmp)
            content, sequence, metrics = _prepare(
                _resolve_structure(merged, scratch), merged, scratch
            )
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit(
                    {
                        "type": "seed",
                        "seed": seed,
                        "designId": f"{job_id}-{seed}",
                        "sequence": sequence or None,
                        "artifactKey": artifact_key,
                        "metrics": metrics,
                    }
                )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "PDB2PQR_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "pdb2pqr",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "pdb2pqr-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
