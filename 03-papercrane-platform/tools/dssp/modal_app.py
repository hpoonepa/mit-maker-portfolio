# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane secondary-structure assignment with DSSP."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
DSSP_VERSION = "4.6.1"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "ca-certificates",
        "cmake",
        "git",
        "libeigen3-dev",
        "libpcre2-dev",
        "zlib1g-dev",
    )
    .run_commands(
        f"git clone --depth 1 --branch v{DSSP_VERSION} https://github.com/PDB-REDO/dssp.git /opt/dssp",
        "cmake -S /opt/dssp -B /opt/dssp/build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF",
        "cmake --build /opt/dssp/build --parallel 4",
        "cmake --install /opt/dssp/build",
    )
)
app = modal.App("papercrane-dssp", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-dssp/1"})
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


def _run_command(command: list[str]) -> None:
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = completed.stderr or completed.stdout
        raise RuntimeError(
            f"mkdssp exited with {completed.returncode}: {detail[-2000:]}"
        )


def _analyze(
    input_path: Path, merged: dict[str, Any], scratch: Path
) -> tuple[dict[str, float], bytes]:
    annotated_path = scratch / "dssp-annotated.cif"
    legacy_path = scratch / "assignments.dssp"
    common = [
        "mkdssp",
        f"--min-pp-stretch={int(merged.get('minPpStretch', 3))}",
    ]
    if bool(merged.get("writeOther", True)):
        common.append("--write-other")
    _run_command(
        [*common, "--output-format=mmcif", str(input_path), str(annotated_path)]
    )
    _run_command([*common, "--output-format=dssp", str(input_path), str(legacy_path)])
    content = annotated_path.read_bytes()
    if not content.lstrip().startswith(b"data_"):
        raise RuntimeError("mkdssp produced no annotated mmCIF output")
    return _parse_legacy(legacy_path.read_text(errors="replace")), content


def _parse_legacy(text: str) -> dict[str, float]:
    in_records = False
    counts: Counter[str] = Counter()
    chains: set[str] = set()
    accessibilities: list[float] = []
    for line in text.splitlines():
        if not in_records:
            if "#  RESIDUE AA STRUCTURE" in line:
                in_records = True
            continue
        if len(line) < 17 or line[13:14] == "!":
            continue
        code = line[16:17]
        counts[code if code.strip() else " "] += 1
        chain = line[11:12].strip()
        if chain:
            chains.add(chain)
        try:
            accessibilities.append(float(line[34:38].strip()))
        except ValueError:
            pass
    residue_count = sum(counts.values())
    if residue_count == 0:
        raise RuntimeError("mkdssp legacy output contained no residue assignments")
    helix_count = sum(counts[code] for code in ("H", "G", "I", "P"))
    beta_count = counts["E"] + counts["B"]
    return {
        "residue_count": float(residue_count),
        "chain_count": float(len(chains) or 1),
        "alpha_helix_residue_count": float(counts["H"]),
        "strand_residue_count": float(counts["E"]),
        "beta_bridge_residue_count": float(counts["B"]),
        "turn_residue_count": float(counts["T"]),
        "bend_residue_count": float(counts["S"]),
        "loop_residue_count": float(counts[" "]),
        "helix_fraction": helix_count / residue_count,
        "beta_fraction": beta_count / residue_count,
        "mean_accessibility": (
            sum(accessibilities) / len(accessibilities) if accessibilities else 0.0
        ),
    }


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/dssp/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-dssp-") as tmp:
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
                "code": "DSSP_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "dssp",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "dssp-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN"})
    )
