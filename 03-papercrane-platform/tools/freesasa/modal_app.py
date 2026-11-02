# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane solvent-accessible surface calculation with FreeSASA."""

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

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential")
    .pip_install("freesasa==2.2.1", "biopython==1.85")
)
app = modal.App("papercrane-freesasa", image=image)


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
        url, headers={"User-Agent": "papercrane-freesasa/1"}
    )
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


def _convert(path: Path, scratch: Path) -> tuple[Path, bytes]:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBIO, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("input", str(path))
    pdb_path = scratch / "input.pdb"
    pdb_writer = PDBIO()
    pdb_writer.set_structure(structure)
    pdb_writer.save(str(pdb_path))
    output = io.StringIO()
    cif_writer = MMCIFIO()
    cif_writer.set_structure(structure)
    cif_writer.save(output)
    return pdb_path, output.getvalue().encode("utf-8")


def _calculate(pdb_path: Path, merged: dict[str, Any]) -> dict[str, float]:
    import freesasa

    parameters = freesasa.Parameters(
        {
            "algorithm": str(merged.get("algorithm") or "LeeRichards"),
            "probe-radius": float(merged.get("probeRadius", 1.4)),
        }
    )
    structure = freesasa.Structure(str(pdb_path))
    result = freesasa.calc(structure, parameters)
    totals = {"polar": 0.0, "apolar": 0.0, "mainChain": 0.0, "sideChain": 0.0}
    residue_count = 0
    for chain in result.residueAreas().values():
        for area in chain.values():
            residue_count += 1
            for name in totals:
                totals[name] += float(getattr(area, name))
    return {
        "total_sasa": float(result.totalArea()),
        "polar_sasa": totals["polar"],
        "apolar_sasa": totals["apolar"],
        "backbone_sasa": totals["mainChain"],
        "sidechain_sasa": totals["sideChain"],
        "residue_count": float(residue_count),
        "probe_radius": float(merged.get("probeRadius", 1.4)),
    }


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/freesasa/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-freesasa-") as tmp:
            scratch = Path(tmp)
            pdb_path, content = _convert(_resolve_structure(merged, scratch), scratch)
            metrics = _calculate(pdb_path, merged)
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
                "code": "FREESASA_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "freesasa",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "freesasa-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
