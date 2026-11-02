# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for the official open-source ESMFold v1 model."""

from __future__ import annotations

import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "30"))
CACHE_NAME = "papercrane-esmfold-cache"
CACHE_DIR = f"/{CACHE_NAME}"
CACHE_VOLUME = modal.Volume.from_name(CACHE_NAME, create_if_missing=True)
OPENFOLD_COMMIT = "4b41059694619831a7db195b7e0988fc4ff3a307"


def _prefetch_model() -> None:
    os.environ["TORCH_HOME"] = CACHE_DIR
    import esm

    model = esm.pretrained.esmfold_v1()
    del model


image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-devel-ubuntu22.04",
        add_python="3.9",
    )
    .apt_install("git", "build-essential")
    .run_commands(
        "python -m pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.1.2",
        "python -m pip install 'fair-esm[esmfold]==2.0.0' biopython==1.85",
        "python -m pip install 'dllogger @ git+https://github.com/NVIDIA/dllogger.git'",
        f"python -m pip install 'openfold @ git+https://github.com/aqlaboratory/openfold.git@{OPENFOLD_COMMIT}'",
    )
    .env({"TORCH_HOME": CACHE_DIR})
    .run_function(_prefetch_model, gpu="A100-40GB", volumes={CACHE_DIR: CACHE_VOLUME})
)

app = modal.App("papercrane-esmfold", image=image)
_MODEL: Any = None


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
    tool_params = base.get("toolParams")
    return {**base, **(tool_params if isinstance(tool_params, dict) else {})}


def _normalize_sequences(merged: dict[str, Any]) -> list[dict[str, str]]:
    raw = merged.get("sequences")
    if not isinstance(raw, list) or not raw:
        single = merged.get("sequence") or merged.get("targetSeq")
        raw = [single] if single else []
    records: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            identifier = str(item.get("id") or f"seq-{index + 1}")
            sequence = str(item.get("sequence") or "")
        else:
            identifier = f"seq-{index + 1}"
            sequence = str(item)
        sequence = "".join(sequence.split()).upper()
        chains = sequence.split(":")
        if not sequence or any(not chain for chain in chains):
            continue
        invalid = set("".join(chains)) - set("ACDEFGHIKLMNPQRSTVWY")
        if invalid:
            raise ValueError(f"sequence {identifier!r} contains unsupported residues: {sorted(invalid)}")
        if sum(map(len, chains)) > 2000:
            raise ValueError("ESMFold adapter limits total sequence length to 2000 residues")
        records.append({"id": identifier, "sequence": sequence})
    if not records:
        raise ValueError("ESMFold requires at least one protein sequence")
    return records


def _model(chunk_size: int):
    global _MODEL
    if _MODEL is None:
        import esm

        _MODEL = esm.pretrained.esmfold_v1().eval().cuda()
    _MODEL.set_chunk_size(chunk_size)
    return _MODEL


def _pdb_to_cif(pdb_text: str) -> tuple[bytes, dict[str, float]]:
    from Bio.PDB import MMCIFIO, PDBParser

    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("esmfold", io.StringIO(pdb_text))
    residue_scores = [
        float(residue["CA"].get_bfactor())
        for residue in structure.get_residues()
        if residue.id[0] == " " and "CA" in residue
    ]
    if not residue_scores:
        raise RuntimeError("ESMFold output contains no protein CA atoms")
    with tempfile.NamedTemporaryFile(suffix=".cif") as handle:
        writer = MMCIFIO()
        writer.set_structure(structure)
        writer.save(handle.name)
        content = Path(handle.name).read_bytes()
    metrics = {
        "mean_plddt": sum(residue_scores) / len(residue_scores),
        "min_plddt": min(residue_scores),
        "max_plddt": max(residue_scores),
        "residue_count": float(len(residue_scores)),
    }
    return content, metrics


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/esmfold/{seed}.cif"
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


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    memory=32768,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    merged = _merged_params(params)
    records = _normalize_sequences(merged)
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or range(len(records)))]
    num_recycles = int(merged.get("numRecycles", merged.get("num_recycles", 4)))
    chunk_size = int(merged.get("chunkSize", merged.get("chunk_size", 128)))
    model = _model(chunk_size)
    import torch

    completed = 0
    for seed in seed_values:
        record = records[((seed - 1) if seed > 0 else seed) % len(records)]
        with torch.no_grad():
            pdb_text = model.infer_pdb(record["sequence"], num_recycles=num_recycles)
        content, metrics = _pdb_to_cif(pdb_text)
        artifact_key = _upload(merged, seed, content)
        _emit({
            "type": "seed",
            "seed": seed,
            "designId": f"{job_id}-{record['id']}",
            "sequence": record["sequence"].replace(":", ""),
            "artifactKey": artifact_key,
            "metrics": metrics,
        })
        completed += 1
    summary = {
        "tool": "esmfold",
        "completed": completed,
        "input_sequences": len(records),
        "requested_seeds": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    sequence = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
    papercrane_dispatch.remote(
        "esmfold-smoke",
        json.dumps([0]),
        json.dumps({"sequences": [{"id": "ubiquitin", "sequence": sequence}]}),
    )
