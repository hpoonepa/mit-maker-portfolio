# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane PDB cleanup and validation with pdb-tools."""

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
PDB_TOOLS_VERSION = "2.7.0"

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    f"pdb-tools=={PDB_TOOLS_VERSION}", "biopython==1.87"
)
app = modal.App("papercrane-pdb-tools", image=image)


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
        url, headers={"User-Agent": "papercrane-pdb-tools/1"}
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


def _to_pdb(path: Path, output_path: Path) -> None:
    from Bio.PDB import MMCIFParser, PDBIO, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(str(output_path))


def _stats(path: Path) -> dict[str, int]:
    from Bio.PDB import PDBParser

    structure = PDBParser(QUIET=True).get_structure("input", str(path))
    atoms = list(structure.get_atoms())
    residues = list(structure.get_residues())
    chains = list(structure.get_chains())
    return {
        "atoms": len(atoms),
        "residues": len(residues),
        "chains": len(chains),
        "heteroatoms": sum(atom.get_parent().id[0] != " " for atom in atoms),
        "hydrogens": sum(str(atom.element).upper() == "H" for atom in atoms),
    }


def _transform(command: list[str], current: Path, destination: Path) -> Path:
    completed = subprocess.run(
        [*command, str(current)],
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(
            f"{' '.join(command)} exited with {completed.returncode}: {detail}"
        )
    if not completed.stdout.strip():
        raise RuntimeError(f"{' '.join(command)} produced an empty structure")
    destination.write_text(completed.stdout)
    return destination


def _clean(
    pdb_path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[Path, dict[str, float]]:
    before = _stats(pdb_path)
    current = pdb_path
    step = 0
    chains = merged.get("chains")
    if isinstance(chains, list) and chains:
        selected = []
        for chain in chains:
            value = str(chain).strip()
            if not value.isalnum() or len(value) > 2:
                raise ValueError(f"invalid PDB chain identifier: {chain}")
            selected.append(value)
        step += 1
        current = _transform(
            ["pdb_selchain", f"-{','.join(selected)}"],
            current,
            scratch / f"step-{step}.pdb",
        )
    if bool(merged.get("removeHeteroatoms", False)):
        step += 1
        current = _transform(["pdb_delhetatm"], current, scratch / f"step-{step}.pdb")
    if bool(merged.get("removeHydrogens", False)):
        step += 1
        current = _transform(
            ["pdb_delelem", "-H"], current, scratch / f"step-{step}.pdb"
        )
    step += 1
    cleaned = _transform(["pdb_tidy"], current, scratch / f"step-{step}.pdb")
    validation = subprocess.run(
        ["pdb_validate", str(cleaned)],
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if validation.returncode not in {0, 1}:
        detail = (validation.stderr or validation.stdout)[-2000:]
        raise RuntimeError(
            f"pdb_validate exited with {validation.returncode}: {detail}"
        )
    issues = [
        line for line in validation.stdout.splitlines() if line.strip().startswith("[!")
    ]
    after = _stats(cleaned)
    metrics = {
        "input_atom_count": float(before["atoms"]),
        "atom_count": float(after["atoms"]),
        "residue_count": float(after["residues"]),
        "chain_count": float(after["chains"]),
        "heteroatom_count": float(after["heteroatoms"]),
        "hydrogen_count": float(after["hydrogens"]),
        "removed_atom_count": float(max(0, before["atoms"] - after["atoms"])),
        "removed_residue_count": float(max(0, before["residues"] - after["residues"])),
        "validation_issue_count": float(len(issues)),
    }
    return cleaned, metrics


def _to_cif(path: Path) -> bytes:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("cleaned", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/pdb-tools/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=1.0, memory=2048)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-pdb-tools-") as tmp:
            scratch = Path(tmp)
            input_pdb = scratch / "input.pdb"
            _to_pdb(_resolve_structure(merged, scratch), input_pdb)
            cleaned, metrics = _clean(input_pdb, merged, scratch)
            content = _to_cif(cleaned)
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
                "code": "PDB_TOOLS_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "pdb-tools",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "pdb-tools-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
