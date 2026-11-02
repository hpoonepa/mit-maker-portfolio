# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane docking-model quality assessment with DockQ."""

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
DOCKQ_VERSION = "2.1.3"

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "numpy==1.26.4", "biopython==1.87", f"DockQ=={DOCKQ_VERSION}"
)
app = modal.App("papercrane-dockq", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-dockq/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_value(ref: Any, raw: Any, url: Any, scratch: Path, stem: str) -> Path:
    if url:
        suffix = (
            ".cif"
            if ".cif" in str(url).lower() or ".mmcif" in str(url).lower()
            else ".pdb"
        )
        return _download(str(url), scratch / f"{stem}{suffix}")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"{stem}{suffix}"
        path.write_text(str(raw))
        return path
    if not ref:
        raise ValueError(f"DockQ requires an explicit {stem} structure")
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / f"{stem}.cif",
        )
    raise ValueError(f"{stem} must be a 4-character PDB id, local path, text, or URL")


def _resolve_inputs(merged: dict[str, Any], scratch: Path) -> tuple[Path, Path]:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    model = _resolve_value(
        merged.get("targetPdb"),
        merged.get("targetPdbText"),
        internal.get("targetStructureUrl") or merged.get("targetPdbUrl"),
        scratch,
        "model",
    )
    native = _resolve_value(
        merged.get("referencePdb") or merged.get("partnerPdb"),
        merged.get("referencePdbText") or merged.get("partnerPdbText"),
        internal.get("partnerStructureUrl")
        or merged.get("referencePdbUrl")
        or merged.get("partnerPdbUrl"),
        scratch,
        "native",
    )
    return model, native


def _model_cif(path: Path) -> bytes:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("model", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _score(
    model: Path, native: Path, merged: dict[str, Any], scratch: Path
) -> dict[str, float]:
    output_path = scratch / "dockq.json"
    allowed_mismatches = int(merged.get("allowedMismatches", 0))
    if not 0 <= allowed_mismatches <= 100:
        raise ValueError("allowedMismatches must be between 0 and 100")
    command = [
        "DockQ",
        str(model),
        str(native),
        "--json",
        str(output_path),
        "--n_cpu",
        "4",
        "--allowed_mismatches",
        str(allowed_mismatches),
        "--short",
    ]
    mapping = merged.get("mapping")
    if mapping:
        mapping_text = str(mapping).strip()
        if ":" not in mapping_text or len(mapping_text) > 100:
            raise ValueError("DockQ mapping must use MODELCHAINS:NATIVECHAINS syntax")
        command.extend(["--mapping", mapping_text])
    if bool(merged.get("noAlign", False)):
        command.append("--no_align")
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2500:]
        raise RuntimeError(f"DockQ exited with {completed.returncode}: {detail}")
    if not output_path.exists():
        raise RuntimeError("DockQ did not produce its JSON result")
    result = json.loads(output_path.read_text())
    interfaces = result.get("best_result")
    if not isinstance(interfaces, dict) or not interfaces:
        raise RuntimeError("DockQ did not identify a native interface")
    values = [entry for entry in interfaces.values() if isinstance(entry, dict)]
    if not values:
        raise RuntimeError("DockQ returned no parseable interface scores")

    def numbers(name: str) -> list[float]:
        return [
            float(entry[name])
            for entry in values
            if isinstance(entry.get(name), (int, float))
        ]

    dockq_values = numbers("DockQ")
    if not dockq_values:
        raise RuntimeError("DockQ result did not include DockQ scores")
    metrics = {
        "global_dockq": float(
            result.get("GlobalDockQ", sum(dockq_values) / len(dockq_values))
        ),
        "total_dockq": float(result.get("best_dockq", sum(dockq_values))),
        "interface_count": float(len(dockq_values)),
        "mean_dockq": sum(dockq_values) / len(dockq_values),
        "best_interface_dockq": max(dockq_values),
        "worst_interface_dockq": min(dockq_values),
    }
    for source, target in (
        ("iRMSD", "mean_irmsd"),
        ("LRMSD", "mean_lrmsd"),
        ("fnat", "mean_fnat"),
        ("fnonnat", "mean_fnonnat"),
        ("F1", "mean_f1"),
        ("clashes", "mean_clashes"),
    ):
        metric_values = numbers(source)
        metrics[target] = (
            sum(metric_values) / len(metric_values) if metric_values else 0.0
        )
    return metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/dockq/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-dockq-") as tmp:
            scratch = Path(tmp)
            model, native = _resolve_inputs(merged, scratch)
            content = _model_cif(model)
            metrics = _score(model, native, merged, scratch)
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
                "code": "DOCKQ_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "dockq",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "dockq-smoke",
        json.dumps([0]),
        json.dumps({"targetPdb": "1BRS", "referencePdb": "1BRS"}),
    )
