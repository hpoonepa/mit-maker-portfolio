# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for the open-source ImmuneBuilder models."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

GPU = os.environ.get("GPU", "A10G")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "30"))
CACHE_DIR = "/papercrane-immunebuilder-cache"
CACHE_VOLUME = modal.Volume.from_name("papercrane-immunebuilder-cache", create_if_missing=True)
ANARCI_COMMIT = "79f6c575056dedef86cb8f405ebb039197923eec"

image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git", "hmmer")
    .run_commands(
        "python -m pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.1.2",
        "python -m pip install openmm==8.5.2 'pdbfixer @ git+https://github.com/openmm/pdbfixer.git@94cfa4c' biopython==1.83",
        f"python -m pip install 'anarci @ git+https://github.com/oxpig/ANARCI.git@{ANARCI_COMMIT}' ImmuneBuilder==1.2",
    )
    .env({"TORCH_HOME": CACHE_DIR})
)

app = modal.App("papercrane-immunebuilder", image=image)
_PREDICTORS: dict[str, Any] = {}


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


def _sequence_values(merged: dict[str, Any]) -> list[tuple[str, str]]:
    values = merged.get("sequences")
    if not isinstance(values, list):
        values = []
    result: list[tuple[str, str]] = []
    for index, value in enumerate(values):
        if isinstance(value, str):
            label, sequence = "", value
        elif isinstance(value, dict):
            label, sequence = str(value.get("id") or ""), str(value.get("sequence") or "")
        else:
            continue
        sequence = "".join(sequence.split()).upper()
        if not sequence or any(aa not in "ACDEFGHIKLMNPQRSTVWY" for aa in sequence):
            raise ValueError(f"sequence {index + 1} must contain only canonical amino acids")
        result.append((label.upper(), sequence))
    if not result:
        raise ValueError("ImmuneBuilder requires receptor sequences")
    return result


def _receptor_sequences(merged: dict[str, Any]) -> tuple[str, dict[str, str]]:
    receptor_type = str(merged.get("receptorType") or "antibody").lower()
    values = _sequence_values(merged)
    expected = {"antibody": ("H", "L"), "nanobody": ("H",), "tcr": ("A", "B")}
    if receptor_type not in expected:
        raise ValueError("receptorType must be antibody, nanobody, or tcr")
    labels = expected[receptor_type]
    if len(values) != len(labels):
        raise ValueError(f"{receptor_type} requires {len(labels)} sequence(s)")
    provided = {label: sequence for label, sequence in values if label in labels}
    if len(provided) == len(labels):
        return receptor_type, provided
    return receptor_type, {label: values[index][1] for index, label in enumerate(labels)}


def _predictor(receptor_type: str) -> Any:
    if receptor_type not in _PREDICTORS:
        from ImmuneBuilder import ABodyBuilder2, NanoBodyBuilder2, TCRBuilder2

        classes = {"antibody": ABodyBuilder2, "nanobody": NanoBodyBuilder2, "tcr": TCRBuilder2}
        _PREDICTORS[receptor_type] = classes[receptor_type]()
    return _PREDICTORS[receptor_type]


def _pdb_to_cif(path: Path) -> tuple[bytes, dict[str, float]]:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("prediction", str(path))
    errors = [float(atom.bfactor) for atom in structure.get_atoms() if atom.get_name() == "CA"]
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    metrics = {
        "mean_predicted_error": sum(errors) / len(errors) if errors else 0.0,
        "max_predicted_error": max(errors) if errors else 0.0,
        "residue_count": float(len(errors)),
    }
    return output.getvalue().encode("utf-8"), metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/immunebuilder/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(str(record["url"]), data=content, method="PUT", headers={"Content-Type": "chemical/x-cif"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU, memory=16384, volumes={CACHE_DIR: CACHE_VOLUME})
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        receptor_type, sequences = _receptor_sequences(merged)
        sequence_text = "".join(sequences.values())
        with tempfile.TemporaryDirectory(prefix="papercrane-immunebuilder-") as tmp:
            pdb_path = Path(tmp) / "prediction.pdb"
            prediction = _predictor(receptor_type).predict(sequences)
            prediction.save(str(pdb_path))
            content, metrics = _pdb_to_cif(pdb_path)
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": sequence_text, "artifactKey": artifact_key,
                    "metrics": {**metrics, "chain_count": float(len(sequences))},
                })
    except Exception as exc:
        _emit({"type": "error", "code": "IMMUNEBUILDER_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "immunebuilder", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "immunebuilder-smoke", json.dumps([0]),
        json.dumps({"receptorType": "nanobody", "sequences": [{"id": "H", "sequence": "QVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISGSGGSTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAKDRWGQGTLVTVSS"}]}),
    )
