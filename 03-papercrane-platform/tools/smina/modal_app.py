# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane CPU protein-ligand docking with smina."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))
SMINA_BIN = "/usr/local/bin/smina"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "ca-certificates")
    .run_commands(
        "curl -fL https://sourceforge.net/projects/smina/files/smina.static/download -o /usr/local/bin/smina",
        "echo 'ffe5e1e78c947f76b0df8805e2c54383d0bbaf2e827a633b643a708cf682a958  /usr/local/bin/smina' | sha256sum -c -",
        "chmod 0755 /usr/local/bin/smina",
    )
    .pip_install("rdkit==2025.3.5", "biopython==1.85")
)
app = modal.App("papercrane-smina", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-smina/1"})
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
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "1VSN"
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


def _protein_receptor(path: Path, scratch: Path) -> tuple[Path, str]:
    from Bio.PDB import PDBIO, MMCIFParser, PDBParser, Select

    class ProteinOnly(Select):
        def accept_model(self, model: Any) -> bool:
            return bool(model.id == 0)

        def accept_residue(self, residue: Any) -> bool:
            return bool(residue.id[0] == " ")

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("receptor", str(path))
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
    receptor_pdb = scratch / "receptor.pdb"
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(str(receptor_pdb), select=ProteinOnly())
    if not any(
        line.startswith("ATOM  ") for line in receptor_pdb.read_text().splitlines()
    ):
        raise ValueError("target structure contains no protein atoms")
    return receptor_pdb, sequence


def _resolve_ligand(
    merged: dict[str, Any], scratch: Path
) -> tuple[Path, list[float], bool]:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    ligand_path = scratch / "ligand.sdf"
    url = internal.get("ligandStructureUrl") or merged.get("ligandSdfUrl")
    molecule = None
    generated_from_smiles = False
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
                    "smina requires an uploaded SDF ligand or ligandSmiles"
                )
            molecule = Chem.MolFromSmiles(smiles.strip())
            generated_from_smiles = True
    if molecule is None:
        raise ValueError("ligand could not be parsed")
    molecule = Chem.AddHs(molecule, addCoords=True)
    needs_embedding = molecule.GetNumConformers() == 0
    if not needs_embedding:
        needs_embedding = not molecule.GetConformer().Is3D()
    if needs_embedding:
        molecule.RemoveAllConformers()
        if AllChem.EmbedMolecule(molecule, randomSeed=0xC0FFEE) != 0:
            raise ValueError("failed to generate a 3D ligand conformer")
        if AllChem.MMFFHasAllMoleculeParams(molecule):
            AllChem.MMFFOptimizeMolecule(molecule)
        else:
            AllChem.UFFOptimizeMolecule(molecule)
    writer = Chem.SDWriter(str(ligand_path))
    writer.write(molecule)
    writer.close()
    conformer = molecule.GetConformer()
    center = [
        sum(
            conformer.GetAtomPosition(index)[axis]
            for index in range(molecule.GetNumAtoms())
        )
        / molecule.GetNumAtoms()
        for axis in range(3)
    ]
    return ligand_path, [float(value) for value in center], generated_from_smiles


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
        combined.append(f"HETATM{serial:5d}{line[11:17]}LIG Z{1:4d}{line[26:]}")
    complex_pdb = receptor_pdb.parent / "complex.pdb"
    complex_pdb.write_text("\n".join(combined) + "\nEND\n")
    structure = PDBParser(QUIET=True).get_structure("complex", str(complex_pdb))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _affinities(poses: list[Any], log_text: str) -> list[float]:
    values: list[float] = []
    for molecule in poses:
        for name in molecule.GetPropNames():
            if name.lower() in {"minimizedaffinity", "affinity"}:
                try:
                    values.append(float(molecule.GetProp(name)))
                except ValueError:
                    pass
                break
    if values:
        return values
    for line in log_text.splitlines():
        match = re.match(r"^\s*\d+\s+(-?\d+(?:\.\d+)?)\s+", line)
        if match:
            values.append(float(match.group(1)))
    if not values:
        raise RuntimeError("smina output contained no docking affinities")
    return values


def _dock(
    seed: int, merged: dict[str, Any], scratch: Path
) -> tuple[bytes, str, dict[str, float]]:
    from rdkit import Chem

    receptor_pdb, sequence = _protein_receptor(
        _resolve_structure(merged, scratch), scratch
    )
    ligand_sdf, ligand_center, generated_from_smiles = _resolve_ligand(merged, scratch)
    output_sdf = scratch / "docked.sdf"
    log_path = scratch / "smina.log"
    command = [
        SMINA_BIN,
        "--receptor",
        str(receptor_pdb),
        "--ligand",
        str(ligand_sdf),
        "--cpu",
        "4",
        "--seed",
        str(seed),
        "--exhaustiveness",
        str(int(merged.get("exhaustiveness", 8))),
        "--num_modes",
        str(int(merged.get("numPoses", 9))),
        "--out",
        str(output_sdf),
        "--log",
        str(log_path),
    ]
    center = merged.get("boxCenter")
    size = merged.get("boxSize")
    if center is not None or size is not None:
        if not isinstance(center, list) or not isinstance(size, list):
            raise ValueError("boxCenter and boxSize must be provided together")
        if len(center) != 3 or len(size) != 3:
            raise ValueError("boxCenter and boxSize must contain three numbers")
        for axis, value in zip(("x", "y", "z"), center, strict=True):
            command.extend([f"--center_{axis}", str(float(value))])
        for axis, value in zip(("x", "y", "z"), size, strict=True):
            command.extend([f"--size_{axis}", str(float(value))])
        box_center = [float(value) for value in center]
    else:
        if generated_from_smiles:
            raise ValueError(
                "SMILES ligands require both boxCenter and boxSize because generated coordinates have no receptor-frame position"
            )
        command.extend(
            [
                "--autobox_ligand",
                str(ligand_sdf),
                "--autobox_add",
                str(float(merged.get("autoboxAdd", 4.0))),
            ]
        )
        box_center = ligand_center
    scoring = str(merged.get("scoring") or "default").lower()
    if scoring not in {"default", "vinardo"}:
        raise ValueError("scoring must be default or vinardo")
    if scoring != "default":
        command.extend(["--scoring", scoring])
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    log_text = completed.stdout + "\n" + completed.stderr
    if log_path.is_file():
        log_text += "\n" + log_path.read_text()
    if completed.returncode != 0:
        raise RuntimeError(
            f"smina exited with {completed.returncode}: {log_text[-2000:]}"
        )
    if not output_sdf.is_file():
        raise RuntimeError("smina produced no docked SDF")
    poses = [
        molecule
        for molecule in Chem.SDMolSupplier(str(output_sdf), removeHs=False)
        if molecule is not None
    ]
    if not poses:
        raise RuntimeError("smina produced no readable docked poses")
    affinities = _affinities(poses, log_text)
    ligand_pose = scratch / "ligand_pose.pdb"
    Chem.MolToPDBFile(poses[0], str(ligand_pose), flavor=4)
    metrics = {
        "smina_affinity": float(affinities[0]),
        "pose_count": float(len(poses)),
        "box_center_x": box_center[0],
        "box_center_y": box_center[1],
        "box_center_z": box_center[2],
        "vinardo_scoring": float(scoring == "vinardo"),
    }
    return _combine_as_cif(receptor_pdb, ligand_pose), sequence, metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/smina/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=4.0, memory=8192)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    completed = 0
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-smina-") as tmp:
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
                "code": "SMINA_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {"tool": "smina", "completed": completed, "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "smina-smoke",
        json.dumps([0]),
        json.dumps(
            {
                "targetPdb": "1VSN",
                "ligandSmiles": "c1ccccc1O",
                "boxCenter": [0.0, 0.0, 0.0],
                "boxSize": [22.0, 22.0, 22.0],
            }
        ),
    )
