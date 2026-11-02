# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein-ligand interaction profiling with PLIP."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("openbabel")
    .pip_install(
        "plip==3.0.0", "openbabel-wheel==3.1.1.22", "rdkit==2025.3.5", "biopython==1.85"
    )
)
app = modal.App("papercrane-plip", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-plip/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"target{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"target{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1VSN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.pdb",
            scratch / "target.pdb",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _as_pdb(path: Path, scratch: Path) -> Path:
    if path.suffix.lower() == ".pdb":
        return path
    from Bio.PDB import MMCIFParser, PDBIO

    structure = MMCIFParser(QUIET=True).get_structure("target", str(path))
    output = scratch / "target.pdb"
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(str(output))
    return output


def _ligand_pdb(merged: dict[str, Any], scratch: Path) -> Path | None:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    sdf_path = scratch / "ligand.sdf"
    url = internal.get("ligandStructureUrl") or merged.get("ligandSdfUrl")
    molecule = None
    if url:
        _download(str(url), sdf_path)
        molecule = next(
            (
                mol
                for mol in Chem.SDMolSupplier(str(sdf_path), removeHs=False)
                if mol is not None
            ),
            None,
        )
    else:
        local = merged.get("ligand_sdf")
        if isinstance(local, str) and Path(local).is_file():
            sdf_path.write_bytes(Path(local).read_bytes())
            molecule = next(
                (
                    mol
                    for mol in Chem.SDMolSupplier(str(sdf_path), removeHs=False)
                    if mol is not None
                ),
                None,
            )
        else:
            smiles = merged.get("ligandSmiles") or merged.get("ligand_smiles")
            if isinstance(smiles, str) and smiles.strip():
                molecule = Chem.MolFromSmiles(smiles.strip())
    if molecule is None:
        return None
    molecule = Chem.AddHs(molecule, addCoords=True)
    if molecule.GetNumConformers() == 0:
        if AllChem.EmbedMolecule(molecule, randomSeed=0xC0FFEE) != 0:
            raise ValueError("failed to generate a 3D ligand conformer")
        AllChem.MMFFOptimizeMolecule(molecule)
    ligand_pdb = scratch / "ligand.pdb"
    Chem.MolToPDBFile(molecule, str(ligand_pdb), flavor=4)
    return ligand_pdb


def _combine_pdb(target: Path, ligand: Path | None, scratch: Path) -> Path:
    if ligand is None:
        return target
    target_lines = [
        line
        for line in target.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    ligand_lines = [
        line
        for line in ligand.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    serial = max(
        (int(line[6:11]) for line in target_lines if line[6:11].strip()), default=0
    )
    combined = list(target_lines)
    for line in ligand_lines:
        serial += 1
        combined.append(f"HETATM{serial:5d}{line[11:]}")
    path = scratch / "complex.pdb"
    path.write_text("\n".join(combined) + "\nEND\n")
    return path


def _as_cif(path: Path) -> bytes:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("complex", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _profile(complex_pdb: Path, scratch: Path) -> dict[str, float]:
    output_dir = scratch / "plip-output"
    completed = subprocess.run(
        ["plip", "-f", str(complex_pdb), "-x", "-o", str(output_dir)],
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"PLIP exited with {completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )
    reports = sorted(output_dir.rglob("report.xml"))
    if not reports:
        raise RuntimeError("PLIP produced no XML report")
    root = ET.parse(reports[0]).getroot()
    tags = [element.tag.rsplit("}", 1)[-1].lower() for element in root.iter()]
    interaction_tags = {
        "hydrophobic_interaction": "hydrophobic_interactions",
        "hydrogen_bond": "hydrogen_bonds",
        "water_bridge": "water_bridges",
        "salt_bridge": "salt_bridges",
        "pi_stack": "pi_stacks",
        "pi_cation_interaction": "pi_cation_interactions",
        "halogen_bond": "halogen_bonds",
        "metal_complex": "metal_complexes",
    }
    metrics = {
        metric: float(tags.count(tag)) for tag, metric in interaction_tags.items()
    }
    metrics["binding_sites"] = float(tags.count("bindingsite"))
    metrics["total_interactions"] = float(
        sum(metrics[name] for name in interaction_tags.values())
    )
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/plip/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-plip-") as tmp:
            scratch = Path(tmp)
            target = _as_pdb(_resolve_structure(merged, scratch), scratch)
            complex_pdb = _combine_pdb(target, _ligand_pdb(merged, scratch), scratch)
            metrics = _profile(complex_pdb, scratch)
            content = _as_cif(complex_pdb)
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
                "code": "PLIP_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "plip",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "plip-smoke", json.dumps([0]), json.dumps({"targetPdb": "1VSN"})
    )
