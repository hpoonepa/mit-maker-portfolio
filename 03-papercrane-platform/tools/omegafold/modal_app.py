# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for the open-source OmegaFold model."""

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

GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "45"))
CACHE_DIR = "/root/.cache/omegafold_ckpt"
CACHE_VOLUME = modal.Volume.from_name("papercrane-omegafold-cache", create_if_missing=True)
OMEGAFOLD_COMMIT = "313c873ad190b64506a497c926649e15fcd88fcd"

image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git")
    .run_commands(
        "python -m pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.1.2",
        f"python -m pip install 'omegafold @ git+https://github.com/HeliXonProtein/OmegaFold.git@{OMEGAFOLD_COMMIT}' biopython==1.83",
    )
)

app = modal.App("papercrane-omegafold", image=image)


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


def _records(merged: dict[str, Any]) -> list[dict[str, str]]:
    values = merged.get("sequences")
    if not isinstance(values, list):
        values = [merged.get("sequence")] if merged.get("sequence") else []
    records: list[dict[str, str]] = []
    for index, value in enumerate(values):
        if isinstance(value, str):
            record_id, sequence = f"sequence-{index + 1}", value
        elif isinstance(value, dict):
            record_id, sequence = str(value.get("id") or f"sequence-{index + 1}"), str(value.get("sequence") or "")
        else:
            continue
        sequence = "".join(sequence.split()).upper()
        if not sequence or any(aa not in "ACDEFGHIKLMNPQRSTVWY" for aa in sequence):
            raise ValueError(f"{record_id} must contain only the 20 canonical amino acids")
        records.append({"id": record_id, "sequence": sequence})
    if not records:
        raise ValueError("at least one protein sequence is required")
    return records


def _pdb_to_cif(path: Path) -> tuple[bytes, dict[str, float]]:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("prediction", str(path))
    confidences = [float(atom.bfactor) for atom in structure.get_atoms() if atom.get_name() == "CA"]
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    metrics = {
        "mean_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "min_confidence": min(confidences) if confidences else 0.0,
        "max_confidence": max(confidences) if confidences else 0.0,
    }
    return output.getvalue().encode("utf-8"), metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/omegafold/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(str(record["url"]), data=content, method="PUT", headers={"Content-Type": "chemical/x-cif"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU, memory=24576, volumes={CACHE_DIR: CACHE_VOLUME})
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    records = _records(merged)
    completed = 0
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-omegafold-") as tmp:
            scratch = Path(tmp)
            for seed in seed_values:
                # The worker gives each pooled lane exactly one seed, so a
                # lane-local enumerate() index is always zero. Select by the
                # stable requested seed to cycle across all input records.
                record = records[((seed - 1) if seed > 0 else seed) % len(records)]
                fasta = scratch / f"input-{seed}.fasta"
                output_dir = scratch / f"output-{seed}"
                fasta.write_text(f">{record['id']}\n{record['sequence']}\n")
                command = [
                    "omegafold", str(fasta), str(output_dir),
                    "--model", str(int(merged.get("model", 2))),
                    "--num_cycle", str(int(merged.get("numCycle", 10))),
                    "--subbatch_size", str(int(merged.get("subbatchSize", 128))),
                ]
                subprocess.run(command, check=True, timeout=TIMEOUT_MIN * 60)
                predictions = sorted(output_dir.glob("*.pdb"))
                if not predictions:
                    raise RuntimeError("OmegaFold produced no PDB structure")
                content, metrics = _pdb_to_cif(predictions[0])
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": record["sequence"], "artifactKey": artifact_key, "metrics": metrics,
                })
                completed += 1
    except Exception as exc:
        _emit({"type": "error", "code": "OMEGAFOLD_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "omegafold", "completed": completed, "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("omegafold-smoke", json.dumps([0]), json.dumps({"sequence": "MKTIIALSYIFCLVFADYKDDDDK"}))
