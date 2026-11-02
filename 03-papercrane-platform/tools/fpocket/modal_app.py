# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane binding-pocket detection with fpocket."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
FPOCKET_VERSION = "4.2.3"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "ca-certificates",
        "git",
        "libnetcdf-dev",
    )
    .run_commands(
        f"git clone --depth 1 --branch {FPOCKET_VERSION} https://github.com/Discngine/fpocket.git /opt/fpocket",
        "make -C /opt/fpocket -j4",
        "make -C /opt/fpocket install",
    )
)
app = modal.App("papercrane-fpocket", image=image)


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
        url, headers={"User-Agent": "papercrane-fpocket/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        lower_url = str(url).lower()
        suffix = ".cif" if ".cif" in lower_url or ".mmcif" in lower_url else ".pdb"
        return _download(str(url), scratch / f"input{suffix}")
    raw = merged.get("targetPdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"input{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or "1VSN"
    candidate = Path(str(ref))
    if candidate.exists():
        suffix = ".cif" if candidate.suffix.lower() in {".cif", ".mmcif"} else ".pdb"
        copied = scratch / f"input{suffix}"
        copied.write_bytes(candidate.read_bytes())
        return copied
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / "input.cif",
        )
    raise ValueError(
        "targetPdb must be a 4-character PDB id, local path, or uploaded target"
    )


def _value(block: str, label: str) -> float:
    match = re.search(
        rf"(?m)^\s*{re.escape(label)}\s*:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
        block,
    )
    return float(match.group(1)) if match else 0.0


def _parse_info(text: str) -> dict[str, float]:
    blocks = re.split(r"(?m)^Pocket\s+\d+\s*:\s*$", text)[1:]
    if not blocks:
        return {"pocket_count": 0.0}
    top = blocks[0]
    scores = [_value(block, "Score") for block in blocks]
    return {
        "pocket_count": float(len(blocks)),
        "top_score": _value(top, "Score"),
        "top_druggability_score": _value(top, "Druggability Score"),
        "top_alpha_sphere_count": _value(top, "Number of Alpha Spheres"),
        "top_total_sasa": _value(top, "Total SASA"),
        "top_polar_sasa": _value(top, "Polar SASA"),
        "top_apolar_sasa": _value(top, "Apolar SASA"),
        "top_volume": _value(top, "Volume"),
        "top_flexibility": _value(top, "Flexibility"),
        "mean_pocket_score": sum(scores) / len(scores),
    }


def _analyze(
    input_path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[dict[str, float], bytes]:
    minimum = float(merged.get("minAlphaSphereRadius", 3.0))
    maximum = float(merged.get("maxAlphaSphereRadius", 6.0))
    if minimum >= maximum:
        raise ValueError("minAlphaSphereRadius must be less than maxAlphaSphereRadius")
    command = [
        "fpocket",
        "-f",
        str(input_path),
        "-w",
        "m",
        "-m",
        str(minimum),
        "-M",
        str(maximum),
    ]
    completed = subprocess.run(
        command,
        cwd=scratch,
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 10,
    )
    if completed.returncode != 0:
        detail = completed.stderr or completed.stdout
        raise RuntimeError(
            f"fpocket exited with {completed.returncode}: {detail[-2000:]}"
        )
    output_dir = input_path.parent / f"{input_path.stem}_out"
    info_path = output_dir / f"{input_path.stem}_info.txt"
    cif_path = output_dir / f"{input_path.stem}_out.cif"
    if not info_path.exists() or not cif_path.exists():
        raise RuntimeError("fpocket produced no descriptor file or analyzed mmCIF")
    content = cif_path.read_bytes()
    if not content.lstrip().startswith(b"data_"):
        raise RuntimeError("fpocket's analyzed structure is not valid mmCIF text")
    return _parse_info(info_path.read_text(errors="replace")), content


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/fpocket/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-fpocket-") as tmp:
            scratch = Path(tmp)
            metrics, content = _analyze(
                _resolve_structure(merged, scratch), merged, scratch
            )
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
                "code": "FPOCKET_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "fpocket",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "fpocket-smoke", json.dumps([0]), json.dumps({"targetPdb": "1VSN"})
    )
