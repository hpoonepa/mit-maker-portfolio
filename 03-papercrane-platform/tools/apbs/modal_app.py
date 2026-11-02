# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Poisson–Boltzmann electrostatics with APBS."""

from __future__ import annotations

import io
import json
import math
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
APBS_BIN = "/opt/APBS-3.4.1.Linux/bin/apbs"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("curl", "unzip")
    .run_commands(
        "curl -fL https://github.com/Electrostatics/apbs/releases/download/v3.4.1/APBS-3.4.1.Linux.zip -o /tmp/apbs.zip",
        "echo '750f6a2df7b5a82b69be5c4cb192115c02fa261d0ff52cf1d9632ed1eda8b4f0  /tmp/apbs.zip' | sha256sum -c -",
        "unzip -q /tmp/apbs.zip -d /opt",
    )
    .pip_install(
        "pdb2pqr==3.7.1",
        "propka==3.5.1",
        "biopython==1.85",
    )
)
app = modal.App("papercrane-apbs", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-apbs/1"})
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


def _prepare_pqr(
    path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[Path, bytes, str]:
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
        "--keep-chain",
        "--drop-water",
        "--pdb-output",
        str(prepared_pdb),
        str(input_pdb),
        str(prepared_pqr),
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=TIMEOUT_MIN * 60 - 20,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"PDB2PQR exited with {completed.returncode}: {detail}")
    if not prepared_pdb.is_file() or not prepared_pqr.is_file():
        raise RuntimeError("PDB2PQR did not produce APBS preparation files")
    content, sequence = _pdb_as_cif(prepared_pdb)
    return prepared_pqr, content, sequence


def _pqr_values(pqr_path: Path) -> tuple[list[tuple[float, float, float]], list[float]]:
    coordinates: list[tuple[float, float, float]] = []
    charges: list[float] = []
    for line in pqr_path.read_text().splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        fields = line.split()
        coordinates.append(tuple(float(value) for value in fields[-5:-2]))
        charges.append(float(fields[-2]))
    if not coordinates:
        raise RuntimeError("PDB2PQR produced an empty PQR structure")
    return coordinates, charges


def _write_apbs_input(
    pqr_path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[Path, int]:
    coordinates, _ = _pqr_values(pqr_path)
    extents = [
        max(point[axis] for point in coordinates)
        - min(point[axis] for point in coordinates)
        for axis in range(3)
    ]
    coarse = [max(extent + 30.0, 40.0) for extent in extents]
    fine = [max(extent + 20.0, 30.0) for extent in extents]
    grid_points = int(merged.get("gridPoints", 65))
    if grid_points not in {33, 65, 97, 129}:
        raise ValueError("gridPoints must be one of 33, 65, 97, or 129")
    equation = str(merged.get("equation") or "lpbe").lower()
    if equation not in {"lpbe", "npbe"}:
        raise ValueError("equation must be lpbe or npbe")
    ionic_strength = float(merged.get("ionicStrength", 0.15))
    ion_lines = ""
    if ionic_strength > 0:
        ion_lines = (
            f"    ion charge 1 conc {ionic_strength:.6f} radius 2.0\n"
            f"    ion charge -1 conc {ionic_strength:.6f} radius 2.0\n"
        )
    input_path = scratch / "apbs.in"
    input_path.write_text(
        "read\n"
        f"    mol pqr {pqr_path.name}\n"
        "end\n"
        "elec name protein\n"
        "    mg-auto\n"
        f"    dime {grid_points} {grid_points} {grid_points}\n"
        f"    cglen {coarse[0]:.6f} {coarse[1]:.6f} {coarse[2]:.6f}\n"
        f"    fglen {fine[0]:.6f} {fine[1]:.6f} {fine[2]:.6f}\n"
        "    cgcent mol 1\n"
        "    fgcent mol 1\n"
        "    mol 1\n"
        f"    {equation}\n"
        "    bcfl sdh\n"
        f"    pdie {float(merged.get('soluteDielectric', 2.0)):.6f}\n"
        f"    sdie {float(merged.get('solventDielectric', 78.54)):.6f}\n"
        "    srfm smol\n"
        "    chgm spl2\n"
        "    sdens 10.0\n"
        f"    srad {float(merged.get('probeRadius', 1.4)):.6f}\n"
        "    swin 0.3\n"
        f"    temp {float(merged.get('temperature', 298.15)):.6f}\n"
        f"{ion_lines}"
        "    calcenergy total\n"
        "    calcforce no\n"
        "    write pot dx potential\n"
        "end\n"
        "quit\n"
    )
    return input_path, len(coordinates)


def _parse_dx(path: Path) -> dict[str, float]:
    values: list[float] = []
    in_data = False
    for line in path.read_text().splitlines():
        if "data follows" in line:
            in_data = True
            continue
        if not in_data:
            continue
        if line.startswith(("attribute", "object", "component")):
            break
        for token in line.split():
            try:
                values.append(float(token))
            except ValueError:
                continue
    if not values:
        raise RuntimeError("APBS potential file contained no grid values")
    mean = sum(values) / len(values)
    return {
        "potential_grid_points": float(len(values)),
        "potential_min_kte": float(min(values)),
        "potential_max_kte": float(max(values)),
        "potential_mean_kte": float(mean),
        "potential_rms_kte": float(
            math.sqrt(sum(value * value for value in values) / len(values))
        ),
    }


def _calculate(
    pqr_path: Path, merged: dict[str, Any], scratch: Path
) -> dict[str, float]:
    input_path, atom_count = _write_apbs_input(pqr_path, merged, scratch)
    completed = subprocess.run(
        [APBS_BIN, str(input_path)],
        cwd=scratch,
        text=True,
        capture_output=True,
        check=False,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError(f"APBS exited with {completed.returncode}: {output[-2000:]}")
    energy_matches = re.findall(
        r"Global net ELEC energy\s*=\s*([-+0-9.eEdD]+)\s*kJ/mol", output
    )
    if not energy_matches:
        raise RuntimeError("APBS output contained no global electrostatic energy")
    potential_files = sorted(scratch.glob("potential*.dx"))
    if not potential_files:
        raise RuntimeError("APBS produced no OpenDX potential grid")
    _, charges = _pqr_values(pqr_path)
    metrics = _parse_dx(potential_files[0])
    metrics.update(
        {
            "electrostatic_energy_kj_mol": float(
                energy_matches[-1].replace("D", "E").replace("d", "e")
            ),
            "net_charge": float(sum(charges)),
            "atom_count": float(atom_count),
            "ionic_strength_molar": float(merged.get("ionicStrength", 0.15)),
            "temperature_kelvin": float(merged.get("temperature", 298.15)),
        }
    )
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/apbs/{seed}.cif"
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
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-apbs-") as tmp:
            scratch = Path(tmp)
            pqr_path, content, sequence = _prepare_pqr(
                _resolve_structure(merged, scratch), merged, scratch
            )
            metrics = _calculate(pqr_path, merged, scratch)
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
                "code": "APBS_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "apbs",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "apbs-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
