# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane CPU protein-ligand docking with AutoDock Vina."""

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

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "openbabel")
    .pip_install(
        "vina==1.2.7",
        "meeko==0.7.1",
        "rdkit==2025.3.5",
        "gemmi==0.7.3",
        "prody==2.6.1",
        "openmm==8.5.2",
        "pdbfixer @ git+https://github.com/openmm/pdbfixer.git@94cfa4c",
        "biopython==1.85",
    )
)
app = modal.App("papercrane-autodock-vina", image=image)


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
        url, headers={"User-Agent": "papercrane-autodock-vina/1"}
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
        return _download(str(url), scratch / f"receptor{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"receptor{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1VSN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "receptor.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _resolve_ligand(merged: dict[str, Any], scratch: Path) -> tuple[Path, list[float]]:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    ligand_path = scratch / "ligand.sdf"
    url = internal.get("ligandStructureUrl") or merged.get("ligandSdfUrl")
    if url:
        _download(str(url), ligand_path)
        molecule = next(
            (
                mol
                for mol in Chem.SDMolSupplier(str(ligand_path), removeHs=False)
                if mol is not None
            ),
            None,
        )
    else:
        local = merged.get("ligand_sdf")
        if isinstance(local, str) and Path(local).is_file():
            ligand_path.write_bytes(Path(local).read_bytes())
            molecule = next(
                (
                    mol
                    for mol in Chem.SDMolSupplier(str(ligand_path), removeHs=False)
                    if mol is not None
                ),
                None,
            )
        else:
            smiles = merged.get("ligandSmiles") or merged.get("ligand_smiles")
            if not isinstance(smiles, str) or not smiles.strip():
                raise ValueError(
                    "AutoDock Vina requires an uploaded SDF ligand or ligandSmiles"
                )
            molecule = Chem.MolFromSmiles(smiles.strip())
    if molecule is None:
        raise ValueError("ligand could not be parsed")
    molecule = Chem.AddHs(molecule, addCoords=True)
    if molecule.GetNumConformers() == 0:
        if AllChem.EmbedMolecule(molecule, randomSeed=0xC0FFEE) != 0:
            raise ValueError("failed to generate a 3D ligand conformer")
        AllChem.MMFFOptimizeMolecule(molecule)
    writer = Chem.SDWriter(str(ligand_path))
    writer.write(molecule)
    writer.close()
    conformer = molecule.GetConformer()
    center = [
        sum(conformer.GetAtomPosition(i)[axis] for i in range(molecule.GetNumAtoms()))
        / molecule.GetNumAtoms()
        for axis in range(3)
    ]
    return ligand_path, [float(value) for value in center]


def _prepare_receptor(path: Path, scratch: Path) -> tuple[Path, str]:
    from openmm.app import PDBFile
    from pdbfixer import PDBFixer

    fixer = PDBFixer(filename=str(path))
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.0)
    receptor_pdb = scratch / "receptor_h.pdb"
    with receptor_pdb.open("w") as handle:
        PDBFile.writeFile(fixer.topology, fixer.positions, handle, keepIds=True)
    sequence = "".join(
        {
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
        }.get(residue.name.upper(), "")
        for residue in fixer.topology.residues()
    )
    return receptor_pdb, sequence


def _run_checked(command: list[str], label: str) -> None:
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 20
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} exited with {completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )


def _combine_as_cif(receptor_pdb: Path, ligand_pdb: Path) -> bytes:
    from Bio.PDB import MMCIFIO, PDBParser

    receptor_lines = [
        line
        for line in receptor_pdb.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    ligand_lines = [
        line
        for line in ligand_pdb.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    serial = max(
        (int(line[6:11]) for line in receptor_lines if line[6:11].strip()), default=0
    )
    combined = list(receptor_lines)
    for line in ligand_lines:
        serial += 1
        combined.append(f"{line[:6]}{serial:5d}{line[11:]}")
    complex_pdb = receptor_pdb.parent / "complex.pdb"
    complex_pdb.write_text("\n".join(combined) + "\nEND\n")
    structure = PDBParser(QUIET=True).get_structure("complex", str(complex_pdb))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _dock(
    seed: int, merged: dict[str, Any], scratch: Path
) -> tuple[bytes, str, dict[str, float]]:
    from vina import Vina

    receptor_pdb, sequence = _prepare_receptor(
        _resolve_structure(merged, scratch), scratch
    )
    ligand_sdf, ligand_center = _resolve_ligand(merged, scratch)
    receptor_prefix = scratch / "receptor"
    receptor_pdbqt = scratch / "receptor.pdbqt"
    ligand_pdbqt = scratch / "ligand.pdbqt"
    _run_checked(
        [
            "mk_prepare_receptor.py",
            "-i",
            str(receptor_pdb),
            "-o",
            str(receptor_prefix),
            "-p",
        ],
        "Meeko receptor preparation",
    )
    if not receptor_pdbqt.exists():
        candidates = sorted(scratch.glob("receptor*.pdbqt"))
        if not candidates:
            raise RuntimeError("Meeko produced no receptor PDBQT")
        receptor_pdbqt = candidates[0]
    _run_checked(
        ["mk_prepare_ligand.py", "-i", str(ligand_sdf), "-o", str(ligand_pdbqt)],
        "Meeko ligand preparation",
    )
    center = (
        merged.get("boxCenter")
        if isinstance(merged.get("boxCenter"), list)
        else ligand_center
    )
    box_size = (
        merged.get("boxSize")
        if isinstance(merged.get("boxSize"), list)
        else [22.0, 22.0, 22.0]
    )
    if len(center) != 3 or len(box_size) != 3:
        raise ValueError("boxCenter and boxSize must contain three numbers")
    vina = Vina(sf_name="vina", cpu=4, seed=seed, verbosity=0)
    vina.set_receptor(str(receptor_pdbqt))
    vina.set_ligand_from_file(str(ligand_pdbqt))
    vina.compute_vina_maps(
        center=[float(x) for x in center], box_size=[float(x) for x in box_size]
    )
    num_poses = int(merged.get("numPoses", 9))
    vina.dock(exhaustiveness=int(merged.get("exhaustiveness", 8)), n_poses=num_poses)
    docked_pdbqt = scratch / "docked.pdbqt"
    vina.write_poses(str(docked_pdbqt), n_poses=num_poses, overwrite=True)
    energies = vina.energies(n_poses=num_poses)
    first = [float(value) for value in energies[0]]
    ligand_pose = scratch / "ligand_pose.pdb"
    _run_checked(
        ["obabel", str(docked_pdbqt), "-O", str(ligand_pose), "-f", "1", "-l", "1"],
        "OpenBabel pose conversion",
    )
    metrics = {
        "vina_affinity": first[0],
        "vina_inter": first[1] if len(first) > 1 else 0.0,
        "vina_intra": first[2] if len(first) > 2 else 0.0,
        "vina_torsions": first[3] if len(first) > 3 else 0.0,
        "pose_count": float(len(energies)),
        "box_center_x": float(center[0]),
        "box_center_y": float(center[1]),
        "box_center_z": float(center[2]),
    }
    return _combine_as_cif(receptor_pdb, ligand_pose), sequence, metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/autodock-vina/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=4.0, memory=8192)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    completed = 0
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-autodock-vina-") as tmp:
            root = Path(tmp)
            for seed in seed_values:
                scratch = root / str(seed)
                scratch.mkdir()
                content, sequence, metrics = _dock(seed, merged, scratch)
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
                completed += 1
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "AUTODOCK_VINA_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "autodock-vina",
        "completed": completed,
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "autodock-vina-smoke",
        json.dumps([0]),
        json.dumps({"targetPdb": "1VSN", "ligandSmiles": "c1ccccc1O"}),
    )
