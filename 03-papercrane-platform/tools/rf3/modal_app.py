# /// script
# requires-python = ">=3.12"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for RoseTTAFold3 in Foundry 0.1.9."""

from __future__ import annotations

import csv
import gzip
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

GPU = os.environ.get("GPU", "H100")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "45"))
CACHE_NAME = "papercrane-rf3-cache"
CACHE_DIR = f"/{CACHE_NAME}"
CACHE_VOLUME = modal.Volume.from_name(CACHE_NAME, create_if_missing=True)


def _install_weights() -> None:
    os.environ["FOUNDRY_CHECKPOINT_DIRS"] = CACHE_DIR
    subprocess.run(
        ["foundry", "install", "rf3", "--checkpoint-dir", CACHE_DIR],
        check=True,
    )


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("rc-foundry[rf3]==0.1.9", "biopython==1.85")
    .env({"FOUNDRY_CHECKPOINT_DIRS": CACHE_DIR})
    .run_function(_install_weights, volumes={CACHE_DIR: CACHE_VOLUME})
)

app = modal.App("papercrane-rf3", image=image)


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
            identifier = str(item.get("id") or f"chain-{index + 1}")
            sequence = str(item.get("sequence") or "")
        else:
            identifier = f"chain-{index + 1}"
            sequence = str(item)
        sequence = "".join(sequence.split()).upper()
        if not sequence:
            continue
        invalid = set(sequence) - set("ACDEFGHIKLMNPQRSTVWY")
        if invalid:
            raise ValueError(f"sequence {identifier!r} contains unsupported residues: {sorted(invalid)}")
        records.append({"id": identifier, "sequence": sequence})
    if not records:
        raise ValueError("RF3 requires at least one protein sequence")
    if len(records) > 26:
        raise ValueError("RF3 adapter supports at most 26 protein chains")
    return records


def _ligand_component(merged: dict[str, Any], scratch: Path) -> dict[str, str] | None:
    internal = merged.get("_papercrane")
    ligand_url = internal.get("ligandStructureUrl") if isinstance(internal, dict) else None
    if isinstance(ligand_url, str) and ligand_url:
        destination = scratch / "ligand.sdf"
        request = urllib.request.Request(ligand_url, headers={"User-Agent": "papercrane-rf3/1"})
        with urllib.request.urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())
        return {"path": str(destination)}
    ligand_file = merged.get("ligand_sdf")
    if isinstance(ligand_file, str) and Path(ligand_file).is_file():
        return {"path": str(Path(ligand_file).resolve())}
    smiles = merged.get("ligandSmiles") or merged.get("ligand_smiles")
    if isinstance(smiles, str) and smiles.strip():
        return {"smiles": smiles.strip()}
    ligand = merged.get("ligand")
    if isinstance(ligand, dict):
        if ligand.get("smiles"):
            return {"smiles": str(ligand["smiles"]).strip()}
        ligand = ligand.get("ccd") or ligand.get("ccdCode")
    if isinstance(ligand, str) and ligand.strip():
        value = ligand.strip()
        code = value[4:] if value.upper().startswith("CCD_") else value
        if code.isalnum() and len(code) <= 6:
            return {"ccd_code": code.upper()}
        return {"smiles": value}
    return None


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/rf3/{seed}.cif"
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


def _scalar_metrics(out_dir: Path) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for path in sorted(out_dir.rglob("*_summary_confidences.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for key, value in payload.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics[str(key)[:64]] = float(value)
        if metrics:
            return metrics
    for path in sorted(out_dir.rglob("*_confidences.csv")):
        try:
            with path.open(newline="") as handle:
                row = next(csv.DictReader(handle), None)
        except OSError:
            continue
        if row:
            for key, value in row.items():
                try:
                    metrics[str(key)[:64]] = float(value)
                except (TypeError, ValueError):
                    pass
        if metrics:
            break
    return metrics


def _fold(seed: int, merged: dict[str, Any], scratch: Path) -> tuple[bytes, str, dict[str, float]]:
    records = _normalize_sequences(merged)
    components: list[dict[str, str]] = [
        {"seq": record["sequence"], "chain_id": chr(65 + index)}
        for index, record in enumerate(records)
    ]
    ligand = _ligand_component(merged, scratch)
    if ligand:
        components.append(ligand)
    input_path = scratch / f"input-{seed}.json"
    out_dir = scratch / f"output-{seed}"
    out_dir.mkdir()
    input_path.write_text(json.dumps({"name": f"papercrane-{seed}", "components": components}))
    command = [
        "rf3",
        "fold",
        f"inputs={input_path}",
        f"out_dir={out_dir}",
        f"seed={seed}",
        f"n_recycles={int(merged.get('nRecycles', merged.get('n_recycles', 10)))}",
        f"num_steps={int(merged.get('numSteps', merged.get('num_steps', 200)))}",
        "diffusion_batch_size=1",
        f"early_stopping_plddt_threshold={float(merged.get('earlyStoppingPlddtThreshold', 0.0))}",
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 30,
        env={**os.environ, "PYTHONHASHSEED": str(seed)},
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-3000:]
        raise RuntimeError(f"RF3 exited with {completed.returncode}: {tail}")
    candidates = sorted(out_dir.rglob("*_model.cif")) or sorted(out_dir.rglob("*.cif"))
    if candidates:
        content = candidates[0].read_bytes()
    else:
        compressed = sorted(out_dir.rglob("*_model.cif.gz")) or sorted(out_dir.rglob("*.cif.gz"))
        if not compressed:
            raise RuntimeError("RF3 produced no mmCIF structure")
        content = gzip.decompress(compressed[0].read_bytes())
    sequence = ":".join(record["sequence"] for record in records)
    return content, sequence, _scalar_metrics(out_dir)


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    memory=32768,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    completed = 0
    with tempfile.TemporaryDirectory(prefix="papercrane-rf3-") as tmp:
        scratch = Path(tmp)
        for seed in seed_values:
            content, sequence, metrics = _fold(seed, merged, scratch)
            artifact_key = _upload(merged, seed, content)
            _emit({
                "type": "seed",
                "seed": seed,
                "designId": f"{job_id}-{seed}",
                "sequence": sequence.replace(":", ""),
                "artifactKey": artifact_key,
                "metrics": metrics,
            })
            completed += 1
    summary = {"tool": "rf3", "completed": completed, "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    sequence = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
    papercrane_dispatch.remote(
        "rf3-smoke",
        json.dumps([0]),
        json.dumps({"sequences": [{"id": "ubiquitin", "sequence": sequence}]}),
    )
