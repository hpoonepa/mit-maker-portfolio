# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane binding-pocket prediction with P2Rank."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
P2RANK_VERSION = "2.5.1"
P2RANK_DIR = f"/opt/prank_{P2RANK_VERSION}"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ca-certificates", "openjdk-17-jre-headless", "unzip", "wget")
    .run_commands(
        f"wget -q https://github.com/rdk/p2rank/releases/download/{P2RANK_VERSION}/prank_{P2RANK_VERSION}.zip -O /tmp/p2rank.zip",
        "unzip -q /tmp/p2rank.zip -d /opt",
        f"ln -s {P2RANK_DIR}/prank /usr/local/bin/prank",
    )
    .pip_install("biopython==1.85")
)

app = modal.App("papercrane-p2rank", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-p2rank/1"})
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


def _as_cif(path: Path) -> bytes:
    if path.suffix.lower() in {".cif", ".mmcif"} and path.read_text(
        errors="ignore"
    ).lstrip().startswith("data_"):
        return path.read_bytes()
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("input", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _float(row: dict[str, str], name: str, default: float = 0.0) -> float:
    try:
        return float(row.get(name, default))
    except (TypeError, ValueError):
        return default


def _predict(path: Path, merged: dict[str, Any], scratch: Path) -> dict[str, float]:
    output_dir = scratch / "predictions"
    command = [
        "prank",
        "predict",
        "-f",
        str(path),
        "-o",
        str(output_dir),
        "-threads",
        "4",
    ]
    profile = str(merged.get("profile") or "default")
    if profile != "default":
        command.extend(["-c", profile])
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"P2Rank exited with {completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )
    csv_files = sorted(output_dir.rglob("*_predictions.csv"))
    if not csv_files:
        raise RuntimeError("P2Rank produced no predictions CSV")
    with csv_files[0].open(newline="") as handle:
        rows = [
            {str(key).strip(): str(value).strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    if not rows:
        return {"pocket_count": 0.0}
    top = rows[0]
    metrics = {
        "pocket_count": float(len(rows)),
        "top_score": _float(top, "score"),
        "top_probability": _float(top, "probability"),
        "top_sas_points": _float(top, "sas_points"),
        "top_center_x": _float(top, "center_x"),
        "top_center_y": _float(top, "center_y"),
        "top_center_z": _float(top, "center_z"),
    }
    if len(rows) > 1:
        metrics["second_score"] = _float(rows[1], "score")
        metrics["second_probability"] = _float(rows[1], "probability")
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/p2rank/{seed}.cif"
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
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-p2rank-") as tmp:
            scratch = Path(tmp)
            input_path = _resolve_structure(merged, scratch)
            metrics = _predict(input_path, merged, scratch)
            content = _as_cif(input_path)
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
                "code": "P2RANK_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "p2rank",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "p2rank-smoke", json.dumps([0]), json.dumps({"targetPdb": "1VSN"})
    )
