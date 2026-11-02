# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane residue pKa prediction with PROPKA."""

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

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "propka==3.5.1",
    "biopython==1.85",
)
app = modal.App("papercrane-propka", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-propka/1"})
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


def _normalize(path: Path, scratch: Path) -> tuple[Path, bytes, str]:
    from Bio.PDB import MMCIFIO, PDBIO, MMCIFParser, PDBParser, Select

    class FirstModel(Select):
        def accept_model(self, model: Any) -> bool:
            return bool(model.id == 0)

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    model = next(structure.get_models())
    input_pdb = scratch / "input.pdb"
    pdb_writer = PDBIO()
    pdb_writer.set_structure(structure)
    pdb_writer.save(str(input_pdb), select=FirstModel())
    output = io.StringIO()
    cif_writer = MMCIFIO()
    cif_writer.set_structure(model)
    cif_writer.save(output)
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
    return input_pdb, output.getvalue().encode("utf-8"), sequence


def _parse_summary(report: str, ph: float) -> dict[str, float]:
    entries: list[tuple[str, str, str, float, float]] = []
    in_summary = False
    for line in report.splitlines():
        if "SUMMARY OF THIS PREDICTION" in line:
            in_summary = True
            continue
        if in_summary and line.startswith("Free energy"):
            break
        if not in_summary:
            continue
        parts = line.split()
        if len(parts) < 4 or not re.fullmatch(r"[A-Z0-9+\-]+", parts[0]):
            continue
        try:
            residue_number = str(int(parts[1]))
        except ValueError:
            continue
        try:
            pka = float(parts[2])
            model_pka = float(parts[3])
            chain = "_"
        except ValueError:
            if len(parts) < 5:
                continue
            try:
                pka = float(parts[3])
                model_pka = float(parts[4])
            except ValueError:
                continue
            chain = parts[2]
        entries.append((parts[0], chain, residue_number, pka, model_pka))
    if not entries:
        raise RuntimeError("PROPKA report contained no residue pKa predictions")

    metrics: dict[str, float] = {
        "target_ph": ph,
        "titratable_group_count": float(len(entries)),
    }
    valid: list[float] = []
    shifts: list[float] = []
    sentinel_count = 0
    for group, chain, residue_number, pka, model_pka in entries:
        label = re.sub(
            r"[^A-Za-z0-9]+", "_", f"{group}_{chain}_{residue_number}"
        ).strip("_")
        metrics[f"pka_{label}"] = pka
        if -10.0 <= pka <= 30.0:
            valid.append(pka)
            shifts.append(abs(pka - model_pka))
        else:
            sentinel_count += 1
    metrics["sentinel_pka_count"] = float(sentinel_count)
    if valid:
        metrics.update(
            {
                "mean_pka": float(sum(valid) / len(valid)),
                "min_pka": float(min(valid)),
                "max_pka": float(max(valid)),
                "mean_absolute_model_shift": float(sum(shifts) / len(shifts)),
            }
        )
    pi_match = re.search(r"The pI is\s+([-+0-9.]+)", report)
    if pi_match:
        metrics["isoelectric_point"] = float(pi_match.group(1))
    return metrics


def _analyze(
    input_pdb: Path, merged: dict[str, Any], scratch: Path
) -> dict[str, float]:
    ph = float(merged.get("ph", 7.0))
    command = ["propka3", "--pH", str(ph)]
    if bool(merged.get("keepProtons", False)):
        command.append("--keep-protons")
    command.append(str(input_pdb))
    completed = subprocess.run(
        command,
        cwd=scratch,
        text=True,
        capture_output=True,
        check=False,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"PROPKA exited with {completed.returncode}: {detail}")
    report_path = scratch / f"{input_pdb.stem}.pka"
    if not report_path.is_file():
        raise RuntimeError("PROPKA produced no .pka report")
    return _parse_summary(report_path.read_text(), ph)


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/propka/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-propka-") as tmp:
            scratch = Path(tmp)
            input_pdb, content, sequence = _normalize(
                _resolve_structure(merged, scratch), scratch
            )
            metrics = _analyze(input_pdb, merged, scratch)
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
                "code": "PROPKA_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "propka",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "propka-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
