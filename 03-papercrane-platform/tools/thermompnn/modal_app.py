# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""ThermoMPNN stability-guided mutation adapter for Papercrane."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import modal

GPU = os.environ.get("GPU", "A10")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))
THERMOMPNN_REPO = "/opt/ThermoMPNN"
THERMOMPNN_SHA = "2b04fd370e399911b1fa5848112cc9013f084110"
MODEL_PATH = f"{THERMOMPNN_REPO}/models/thermoMPNN_default.pt"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git")
    .pip_install(
        "torch==2.2.2", "torchvision==0.17.2", "torchaudio==2.2.2",
        index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install(
        "pytorch-lightning==2.2.5", "torchmetrics==1.4.0", "biopython==1.83",
        "pandas==2.2.2", "numpy<2", "omegaconf==2.3.0", "joblib==1.4.2",
        "tqdm==4.66.4", "wandb==0.17.4",
    )
    .run_commands(
        f"git clone https://github.com/Kuhlman-Lab/ThermoMPNN.git {THERMOMPNN_REPO}",
        f"cd {THERMOMPNN_REPO} && git checkout {THERMOMPNN_SHA}",
    )
    .env({"PYTHONPATH": THERMOMPNN_REPO, "WANDB_MODE": "disabled"})
)

app = modal.App("papercrane-thermompnn", image=image)


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


def _download(url: str, destination: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-thermompnn/1"})
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
    raw = merged.get("targetPdbText") or merged.get("target_pdb_str")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"input{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "1CRN"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.pdb",
            scratch / f"{str(ref).lower()}.pdb",
        )
    raise ValueError("targetPdb must be a 4-character PDB id, local path, or uploaded target")


def _normalize_structure(input_path: Path, scratch: Path) -> tuple[Path, bytes]:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBIO, PDBParser

    parser = MMCIFParser(QUIET=True) if input_path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("target", str(input_path))
    pdb_path = scratch / "target.pdb"
    pdb_writer = PDBIO()
    pdb_writer.set_structure(structure)
    pdb_writer.save(str(pdb_path))
    cif_path = scratch / "target.cif"
    cif_writer = MMCIFIO()
    cif_writer.set_structure(structure)
    cif_writer.save(str(cif_path))
    return pdb_path, cif_path.read_bytes()


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/thermompnn/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(
        str(record["url"]), data=content, method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _run_scan(pdb_path: Path, out_dir: Path, chain: str) -> list[dict[str, Any]]:
    command = [
        "python", f"{THERMOMPNN_REPO}/analysis/custom_inference.py",
        "--pdb", str(pdb_path), "--chain", chain,
        "--model_path", MODEL_PATH, "--out_dir", str(out_dir),
    ]
    completed = subprocess.run(
        command, cwd=THERMOMPNN_REPO, text=True, capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 30,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"ThermoMPNN exited with {completed.returncode}: {tail}")
    csv_files = sorted(out_dir.glob("ThermoMPNN_inference_*.csv"))
    if not csv_files:
        raise RuntimeError("ThermoMPNN produced no inference CSV")
    with csv_files[0].open(newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    predictions: list[dict[str, Any]] = []
    for row in rows:
        try:
            predictions.append({
                "ddg": float(row["ddG_pred"]),
                "position": int(float(row["position"])),
                "wildtype": str(row["wildtype"]).strip().upper(),
                "mutation": str(row["mutation"]).strip().upper(),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not predictions:
        raise RuntimeError("ThermoMPNN inference CSV had no valid predictions")
    predictions.sort(key=lambda row: row["ddg"])
    return predictions


def _chain_sequence(pdb_path: Path, chain_id: str) -> tuple[str, dict[int, int]]:
    from Bio.PDB import PDBParser
    from Bio.SeqUtils import seq1

    structure = PDBParser(QUIET=True).get_structure("target", str(pdb_path))
    chain = next((item for item in structure.get_chains() if item.id == chain_id), None)
    if chain is None:
        raise ValueError(f"chain {chain_id!r} was not found in the input structure")
    letters: list[str] = []
    residue_to_index: dict[int, int] = {}
    for residue in chain.get_residues():
        if residue.id[0] != " ":
            continue
        letter = seq1(residue.resname, custom_map={"UNK": "X"})
        if letter == "X":
            continue
        residue_to_index[int(residue.id[1])] = len(letters)
        letters.append(letter)
    return "".join(letters), residue_to_index


def _choose_candidates(predictions: list[dict[str, Any]], merged: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    include_cysteine = bool(merged.get("includeCysteine", False))
    explicit = str(merged.get("mutation") or "").upper()
    candidates = [row for row in predictions if include_cysteine or row["mutation"] != "C"]
    if explicit:
        candidates = [row for row in candidates if f"{row['wildtype']}{row['position']}{row['mutation']}" == explicit]
        if not candidates:
            raise ValueError(f"requested mutation {explicit} was not present in the ThermoMPNN scan")
        return candidates, True
    threshold = float(merged.get("ddgThreshold", -0.5))
    passing = [row for row in candidates if row["ddg"] <= threshold]
    return (passing or candidates), bool(passing)


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU, memory=16384)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    chain = str(merged.get("chain") or merged.get("targetChain") or "A")
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-thermompnn-") as tmp:
            scratch = Path(tmp)
            source = _resolve_structure(merged, scratch)
            pdb_path, structure_bytes = _normalize_structure(source, scratch)
            sequence, residue_to_index = _chain_sequence(pdb_path, chain)
            scan_dir = scratch / "scan"
            scan_dir.mkdir()
            predictions = _run_scan(pdb_path, scan_dir, chain)
            candidates, has_passing = _choose_candidates(predictions, merged)
            for seed in seed_values:
                candidate_index = seed % len(candidates)
                candidate = candidates[candidate_index]
                position = int(candidate["position"])
                sequence_index = residue_to_index.get(position, position - 1)
                if not 0 <= sequence_index < len(sequence):
                    raise ValueError(f"mutation position {position} is outside chain {chain}")
                designed = list(sequence)
                designed[sequence_index] = str(candidate["mutation"])
                mutation_label = f"{candidate['wildtype']}{position}{candidate['mutation']}"
                artifact_key = _upload(merged, seed, structure_bytes)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": "".join(designed), "artifactKey": artifact_key,
                    "metrics": {
                        "ddg": float(candidate["ddg"]), "position": float(position),
                        "rank": float(candidate_index + 1), "passes_threshold": 1.0 if has_passing else 0.0,
                    },
                    "mutation": mutation_label,
                })
    except Exception as exc:
        _emit({"type": "error", "code": "THERMOMPNN_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "thermompnn", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("thermompnn-smoke", json.dumps([0]), json.dumps({"targetPdb": "1CRN", "chain": "A"}))
