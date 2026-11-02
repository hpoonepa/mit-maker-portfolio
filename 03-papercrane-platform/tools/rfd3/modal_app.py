# /// script
# requires-python = ">=3.12"
# dependencies = ["modal>=1.0"]
# ///
"""RosettaCommons Foundry RFdiffusion3 0.1.9 adapter for Papercrane."""

from __future__ import annotations

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
CHECKPOINT_VOLUME_NAME = "papercrane-rfd3-cache"
CHECKPOINT_DIR = f"/{CHECKPOINT_VOLUME_NAME}"
CHECKPOINT_VOLUME = modal.Volume.from_name(CHECKPOINT_VOLUME_NAME, create_if_missing=True)


def _install_weights() -> None:
    """Download the official RFD3 checkpoint once into a persistent volume."""
    os.environ["FOUNDRY_CHECKPOINT_DIRS"] = CHECKPOINT_DIR
    subprocess.run(
        ["foundry", "install", "rfd3", "--checkpoint-dir", CHECKPOINT_DIR],
        check=True,
    )


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("rc-foundry[rfd3]==0.1.9", "biopython==1.85")
    .env({"FOUNDRY_CHECKPOINT_DIRS": CHECKPOINT_DIR})
    .run_function(_install_weights, volumes={CHECKPOINT_DIR: CHECKPOINT_VOLUME})
)

app = modal.App("papercrane-rfd3", image=image)


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
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-rfd3/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(merged: dict[str, Any], scratch: Path) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get("targetStructureUrl") or merged.get("targetPdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"target{suffix}")
    raw = merged.get("targetPdbText") or merged.get("target_pdb_str")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"target{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get("targetPdb") or merged.get("target_pdb") or "1YCR"
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / f"{str(ref).lower()}.cif",
        )
    raise ValueError("targetPdb must be a 4-character PDB id, local path, or uploaded target")


def _target_span(path: Path, requested_chain: str | None) -> tuple[str, int, int]:
    from Bio.PDB import MMCIFParser, PDBParser

    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("target", str(path))
    protein_chains: list[tuple[str, list[int]]] = []
    for chain in structure.get_chains():
        residues = [int(residue.id[1]) for residue in chain if residue.id[0] == " " and "CA" in residue]
        if residues:
            protein_chains.append((str(chain.id), residues))
    if not protein_chains:
        raise ValueError("target structure contains no protein chain with CA atoms")
    selected = next((item for item in protein_chains if item[0] == requested_chain), None)
    if requested_chain and selected is None:
        raise ValueError(f"target chain {requested_chain!r} was not found")
    chain, residues = selected or protein_chains[0]
    return chain, min(residues), max(residues)


def _hotspot_selection(value: Any, default_chain: str) -> str | None:
    tokens: list[str] = []
    values = value if isinstance(value, list) else ([value] if value else [])
    for hotspot in values:
        if isinstance(hotspot, str):
            tokens.extend(part.strip() for part in hotspot.split(",") if part.strip())
        elif isinstance(hotspot, int):
            tokens.append(f"{default_chain}{hotspot}")
        elif isinstance(hotspot, dict):
            chain = str(hotspot.get("chain") or default_chain)
            residues = hotspot.get("residues")
            if isinstance(residues, list):
                tokens.extend(f"{chain}{int(residue)}" for residue in residues)
            else:
                residue = hotspot.get("resi") or hotspot.get("residue") or hotspot.get("position")
                if residue is not None:
                    tokens.append(f"{chain}{int(residue)}")
    return ",".join(dict.fromkeys(tokens)) or None


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/rfd3/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    request = urllib.request.Request(
        str(record["url"]), data=content, method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _find_design(out_dir: Path) -> tuple[Path, bytes]:
    candidates = [
        path for path in sorted(out_dir.rglob("*.cif"))
        if "traject" not in path.name.lower() and "guidepost" not in path.name.lower()
    ]
    if candidates:
        return candidates[0], candidates[0].read_bytes()
    compressed = [
        path for path in sorted(out_dir.rglob("*.cif.gz"))
        if "traject" not in path.name.lower() and "guidepost" not in path.name.lower()
    ]
    if compressed:
        content = gzip.decompress(compressed[0].read_bytes())
        materialized = out_dir / "design.cif"
        materialized.write_bytes(content)
        return materialized, content
    raise RuntimeError("RFD3 produced no mmCIF design")


def _sequence_from_first_chain(cif_path: Path) -> str:
    from Bio.PDB import MMCIFParser
    from Bio.SeqUtils import seq1

    structure = MMCIFParser(QUIET=True).get_structure("design", str(cif_path))
    for chain in structure.get_chains():
        sequence = "".join(
            seq1(residue.resname, custom_map={"UNK": "X"})
            for residue in chain if residue.id[0] == " " and "CA" in residue
        )
        sequence = sequence.replace("X", "")
        if sequence:
            return sequence
    return ""


def _metrics_for_design(cif_path: Path, binder_length: int) -> dict[str, float]:
    metrics: dict[str, float] = {"binder_length": float(binder_length)}
    json_candidates = sorted(cif_path.parent.glob("*.json"))
    for path in json_candidates:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        stack: list[tuple[str, Any]] = [("", payload)]
        while stack:
            prefix, value = stack.pop()
            if isinstance(value, dict):
                stack.extend((f"{prefix}_{key}" if prefix else str(key), child) for key, child in value.items())
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                lowered = prefix.lower()
                if any(token in lowered for token in ("plddt", "rmsd", "residue_count", "atom_count")):
                    metrics[prefix[-64:]] = float(value)
        if len(metrics) > 1:
            break
    return metrics


def _run_design(target: Path, out_dir: Path, seed: int, merged: dict[str, Any]) -> tuple[bytes, str, dict[str, float]]:
    chain, start, end = _target_span(target, merged.get("targetChain"))
    length_min = int(merged.get("binderLengthMin", 60))
    length_max = int(merged.get("binderLengthMax", 120))
    if length_min > length_max:
        raise ValueError("binderLengthMin cannot exceed binderLengthMax")
    contig = str(merged.get("contig") or f"{length_min}-{length_max},/0,{chain}{start}-{end}")
    hotspots = _hotspot_selection(merged.get("hotspots"), chain)
    specification: dict[str, Any] = {
        "input": str(target),
        "contig": contig,
        "redesign_motif_sidechains": bool(merged.get("redesignMotifSidechains", False)),
        "is_non_loopy": bool(merged.get("isNonLoopy", True)),
        "infer_ori_strategy": "hotspots" if hotspots else "com",
    }
    if hotspots:
        specification["select_hotspots"] = hotspots
    ligand = merged.get("ligand")
    if isinstance(ligand, str) and ligand.strip():
        specification["ligand"] = ligand.strip()
    elif isinstance(ligand, dict) and ligand.get("ccd"):
        specification["ligand"] = str(ligand["ccd"])

    inputs_path = out_dir.parent / f"inputs-{seed}.json"
    inputs_path.write_text(json.dumps({f"papercrane-{seed}": specification}))
    command = [
        "rfd3", "design", f"out_dir={out_dir}", f"inputs={inputs_path}",
        "n_batches=1", "diffusion_batch_size=1", "skip_existing=False",
        "dump_trajectories=False", f"global_prefix=seed{seed}_",
        f"inference_sampler.num_timesteps={int(merged.get('numTimesteps', 200))}",
        f"inference_sampler.step_scale={float(merged.get('stepScale', 1.5))}",
        f"low_memory_mode={str(bool(merged.get('lowMemoryMode', False))).lower()}",
    ]
    environment = {**os.environ, "PYTHONHASHSEED": str(seed), "PL_GLOBAL_SEED": str(seed)}
    completed = subprocess.run(
        command, text=True, capture_output=True, env=environment,
        timeout=TIMEOUT_MIN * 60 - 30,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-3000:]
        raise RuntimeError(f"RFD3 exited with {completed.returncode}: {tail}")
    cif_path, content = _find_design(out_dir)
    sequence = _sequence_from_first_chain(cif_path)
    return content, sequence, _metrics_for_design(cif_path, len(sequence))


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    memory=32768,
    volumes={CHECKPOINT_DIR: CHECKPOINT_VOLUME},
)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-rfd3-") as tmp:
            scratch = Path(tmp)
            target = _resolve_structure(merged, scratch)
            for seed in seed_values:
                out_dir = scratch / f"output-{seed}"
                out_dir.mkdir()
                content, sequence, metrics = _run_design(target, out_dir, seed, merged)
                artifact_key = _upload(merged, seed, content)
                _emit({
                    "type": "seed", "seed": seed, "designId": f"{job_id}-{seed}",
                    "sequence": sequence or None, "artifactKey": artifact_key, "metrics": metrics,
                })
    except Exception as exc:
        _emit({"type": "error", "code": "RFD3_FAILED", "message": str(exc), "retryable": False})
        raise
    summary = {"tool": "rfd3", "completed": len(seed_values), "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote("rfd3-smoke", json.dumps([0]), json.dumps({"targetPdb": "1YCR", "targetChain": "A", "binderLengthMin": 40, "binderLengthMax": 40}))
