# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""AntiFold 0.3.1 Modal adapter for Papercrane."""

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

GPU = os.environ.get("GPU", "A10")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "20"))
MODEL_PATH = "/opt/antifold/model.pt"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("curl")
    .pip_install(
        "torch==2.2.0",
        index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install("antifold==0.3.1", "biopython==1.83")
    .run_commands(
        "mkdir -p /opt/antifold",
        "curl -fsSL https://opig.stats.ox.ac.uk/data/downloads/AntiFold/models/model.pt -o /opt/antifold/model.pt",
    )
)

app = modal.App("papercrane-antifold", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-antifold/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"antibody{suffix}")
    raw = merged.get("targetPdbText") or merged.get("target_pdb_str")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"antibody{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "6Y1L"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.pdb",
            scratch / f"{str(ref).lower()}.pdb",
        )
    raise ValueError("targetPdb must be a 4-character PDB id, local path, or uploaded target")


def _as_mmcif(input_path: Path, output_path: Path) -> bytes:
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

    parser = MMCIFParser(QUIET=True) if input_path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("antibody", str(input_path))
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(str(output_path))
    return output_path.read_bytes()


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/antifold/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(
        str(record["url"]), data=content, method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _read_design(out_dir: Path) -> tuple[str, dict[str, float]]:
    from Bio import SeqIO

    fasta_files = sorted(out_dir.glob("*.fasta"))
    if not fasta_files:
        fasta_files = sorted(out_dir.rglob("*.fasta"))
    if not fasta_files:
        raise RuntimeError("AntiFold produced no FASTA output")
    records = list(SeqIO.parse(str(fasta_files[0]), "fasta"))
    if not records:
        raise RuntimeError("AntiFold FASTA output was empty")
    record = records[1] if len(records) > 1 else records[0]
    raw_sequence = str(record.seq).upper()
    chains = [part for part in re.split(r"[^ACDEFGHIKLMNPQRSTVWY]+", raw_sequence) if part]
    sequence = "".join(chains)
    metrics: dict[str, float] = {
        "sequence_length": float(len(sequence)),
        "chain_count": float(len(chains)),
        "heavy_chain_length": float(len(chains[0])) if chains else 0.0,
    }
    for key in ("score", "global_score", "seq_recovery", "mutations", "T"):
        match = re.search(rf"(?:^|[, ]){re.escape(key)}=([-+0-9.eE]+)", record.description)
        if match:
            metrics[key.lower()] = float(match.group(1))
    return sequence, metrics


def _run_antifold(input_path: Path, out_dir: Path, seed: int, merged: dict[str, Any]) -> tuple[str, dict[str, float]]:
    command = [
        "python", "-m", "antifold.main",
        "--pdb_file", str(input_path),
        "--out_dir", str(out_dir),
        "--model_path", MODEL_PATH,
        "--num_seq_per_target", "1",
        "--sampling_temp", str(float(merged.get("temperature", 0.2))),
        "--regions", str(merged.get("regions", "CDR1 CDR2 CDR3")),
        "--seed", str(seed),
        "--verbose", "0",
    ]
    heavy = merged.get("heavyChain") or merged.get("heavy_chain") or merged.get("targetChain")
    light = merged.get("lightChain") or merged.get("light_chain")
    antigen = merged.get("antigenChain") or merged.get("antigen_chain")
    if bool(merged.get("nanobody", False)):
        command.extend(["--nanobody_chain", str(heavy or "H"), "--nanobody_mode"])
    else:
        if heavy:
            command.extend(["--heavy_chain", str(heavy)])
        if light:
            command.extend(["--light_chain", str(light)])
    if antigen:
        command.extend(["--antigen_chain", str(antigen), "--custom_chain_mode"])
    if bool(merged.get("limitVariation", False)):
        command.append("--limit_variation")
    completed = subprocess.run(command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 30)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"AntiFold exited with {completed.returncode}: {tail}")
    return _read_design(out_dir)


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU, memory=16384)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [42])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-antifold-") as tmp:
            scratch = Path(tmp)
            input_path = _resolve_structure(merged, scratch)
            structure_bytes = _as_mmcif(input_path, scratch / "antibody.cif")
            for seed in seed_values:
                out_dir = scratch / f"output-{seed}"
                out_dir.mkdir()
                sequence, metrics = _run_antifold(input_path, out_dir, seed, merged)
                artifact_key = _upload(merged, seed, structure_bytes)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": sequence, "artifactKey": artifact_key, "metrics": metrics,
                })
    except Exception as exc:
        _emit({"type": "error", "code": "ANTIFOLD_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "antifold", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("antifold-smoke", json.dumps([42]), json.dumps({"targetPdb": "6Y1L"}))
