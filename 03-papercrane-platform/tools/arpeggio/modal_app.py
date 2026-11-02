# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane interatomic contact analysis with PDBe Arpeggio."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))
ARPEGGIO_VERSION = "1.4.4"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("openbabel", "python3-openbabel")
    .pip_install(
        f"pdbe-arpeggio=={ARPEGGIO_VERSION}", "biopython==1.87", "gemmi==0.7.3"
    )
    .env({"PYTHONPATH": "/usr/lib/python3/dist-packages"})
)
app = modal.App("papercrane-arpeggio", image=image)


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
        url, headers={"User-Agent": "papercrane-arpeggio/1"}
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
        return _download(str(url), scratch / f"source{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"source{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "source.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _to_cif(path: Path, scratch: Path) -> tuple[Path, bytes]:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    content = output.getvalue().encode("utf-8")
    cif_path = scratch / "input.cif"
    cif_path.write_bytes(content)
    return cif_path, content


def _analyse(cif_path: Path, merged: dict[str, Any], scratch: Path) -> dict[str, float]:
    output_dir = scratch / "output"
    ph = float(merged.get("pH", 7.4))
    cutoff = float(merged.get("interactingCutoff", 5.0))
    if not 0 <= ph <= 14 or not 3 <= cutoff <= 10:
        raise ValueError("pH or interactingCutoff is outside supported bounds")
    command = [
        "pdbe-arpeggio",
        "-m",
        "-o",
        str(output_dir),
        "-ph",
        str(ph),
        "-i",
        str(cutoff),
    ]
    if bool(merged.get("includeSequenceAdjacent", False)):
        command.append("-sa")
    selection = merged.get("selection")
    if selection is not None:
        if not isinstance(selection, list):
            raise ValueError("Arpeggio selection must be an array")
        selections = [str(value).strip() for value in selection]
        if any(not value or len(value) > 200 for value in selections):
            raise ValueError(
                "Arpeggio selections must be non-empty and at most 200 characters"
            )
        if any(
            not re.fullmatch(r"[A-Za-z0-9_:/,*+.-]+", value) for value in selections
        ):
            raise ValueError("Arpeggio selection contains unsupported characters")
        if selections:
            command.extend(["-s", *selections])
    command.append(str(cif_path))
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(
            f"PDBe Arpeggio exited with {completed.returncode}: {detail}"
        )
    result_path = output_dir / "input.json"
    if not result_path.exists():
        raise RuntimeError("PDBe Arpeggio did not produce input.json")
    contacts = json.loads(result_path.read_text())
    if not isinstance(contacts, list):
        raise RuntimeError("PDBe Arpeggio returned an invalid contact document")
    contact_types: Counter[str] = Counter()
    geometries: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    distances: list[float] = []
    for entry in contacts:
        if not isinstance(entry, dict):
            continue
        geometries[str(entry.get("type") or "unknown")] += 1
        entities[str(entry.get("interacting_entities") or "unknown")] += 1
        labels = entry.get("contact")
        if isinstance(labels, list):
            contact_types.update(str(label).lower() for label in labels)
        distance = entry.get("distance")
        if isinstance(distance, (int, float)):
            distances.append(float(distance))
    metrics = {
        "contact_count": float(len(contacts)),
        "contact_type_occurrences": float(sum(contact_types.values())),
        "atom_atom_contacts": float(geometries["atom-atom"]),
        "atom_plane_contacts": float(geometries["atom-plane"]),
        "plane_plane_contacts": float(geometries["plane-plane"]),
        "group_group_contacts": float(geometries["group-group"]),
        "inter_contacts": float(entities["INTER"]),
        "mean_distance_angstrom": sum(distances) / len(distances) if distances else 0.0,
        "minimum_distance_angstrom": min(distances) if distances else 0.0,
        "maximum_distance_angstrom": max(distances) if distances else 0.0,
    }
    for label in (
        "hbond",
        "weak_hbond",
        "ionic",
        "hydrophobic",
        "aromatic",
        "vdw",
        "vdw_clash",
        "clash",
        "covalent",
        "metal",
        "polar",
        "carbonyl",
    ):
        metrics[f"contacts_{label}"] = float(contact_types[label])
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/arpeggio/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=8192)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-arpeggio-") as tmp:
            scratch = Path(tmp)
            cif_path, content = _to_cif(_resolve_structure(merged, scratch), scratch)
            metrics = _analyse(cif_path, merged, scratch)
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
                "code": "ARPEGGIO_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "arpeggio",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "arpeggio-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
