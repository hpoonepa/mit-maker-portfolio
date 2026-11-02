# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane Modal adapter for DISCO sequence/structure co-design."""

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

GPU = os.environ.get("GPU", "H100")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "90"))
DISCO_COMMIT = "82b594f838eb61dd8c78ae3a403ccb8f00cf7abf"
DISCO_DIR = "/opt/DISCO"
DISCO_PYTHON = f"{DISCO_DIR}/.venv/bin/python"
CACHE_NAME = "papercrane-disco-cache"
CACHE_DIR = f"/{CACHE_NAME}"
CACHE_VOLUME = modal.Volume.from_name(CACHE_NAME, create_if_missing=True)


def _prefetch_weights() -> None:
    code = """
from huggingface_hub import hf_hub_download
from transformers import AutoModelForMaskedLM, AutoTokenizer
for filename in ('DISCO.pt', 'components.v20240608.cif', 'components.v20240608.cif.rdkit_mol.pkl'):
    hf_hub_download(repo_id='DISCO-Design/DISCO', filename=filename)
AutoTokenizer.from_pretrained('airkingbd/dplm_650m')
AutoModelForMaskedLM.from_pretrained('airkingbd/dplm_650m')
"""
    subprocess.run([DISCO_PYTHON, "-c", code], check=True, env={**os.environ, "HF_HOME": CACHE_DIR})


image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-devel-ubuntu22.04",
        add_python="3.11",
    )
    .apt_install("git", "build-essential")
    .pip_install("uv==0.8.15")
    .run_commands(
        f"git clone https://github.com/DISCO-design/DISCO.git {DISCO_DIR}",
        f"cd {DISCO_DIR} && git checkout {DISCO_COMMIT} && uv sync",
        f"cd {DISCO_DIR} && uv pip uninstall torch && uv pip install torch --torch-backend=cu124",
    )
    .env({
        "HF_HOME": CACHE_DIR,
        "TRANSFORMERS_CACHE": CACHE_DIR,
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    .run_function(_prefetch_weights, gpu="H100", volumes={CACHE_DIR: CACHE_VOLUME})
)

app = modal.App("papercrane-disco", image=image)


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


def _protein_template(merged: dict[str, Any]) -> tuple[str, str]:
    raw = merged.get("sequences")
    if isinstance(raw, list) and len(raw) > 1:
        raise ValueError("DISCO currently supports one protein chain per Papercrane job")
    item = raw[0] if isinstance(raw, list) and raw else merged.get("sequenceTemplate")
    identifier = "protein"
    if isinstance(item, dict):
        identifier = str(item.get("id") or identifier)
        item = item.get("sequence")
    supplied = "".join(str(item or "").split()).upper()
    if supplied:
        invalid = set(supplied) - set("ACDEFGHIKLMNPQRSTVWY-")
        if invalid:
            raise ValueError(f"DISCO protein template contains unsupported residues: {sorted(invalid)}")
        template = supplied if bool(merged.get("preserveSequence", False)) else "-" * len(supplied)
    else:
        length = int(merged.get("proteinLength", 150))
        template = "-" * length
    if not 50 <= len(template) <= 500:
        raise ValueError("DISCO protein length must be between 50 and 500 residues")
    return identifier, template


def _download(url: str, destination: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "papercrane-disco/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def _ligand_value(merged: dict[str, Any], scratch: Path) -> str | None:
    internal = merged.get("_papercrane")
    ligand_url = internal.get("ligandStructureUrl") if isinstance(internal, dict) else None
    if isinstance(ligand_url, str) and ligand_url:
        path = _download(ligand_url, scratch / "ligand.sdf")
        return f"FILE_{path}"
    ligand_file = merged.get("ligand_sdf")
    if isinstance(ligand_file, str) and Path(ligand_file).is_file():
        return f"FILE_{Path(ligand_file).resolve()}"
    smiles = merged.get("ligandSmiles") or merged.get("ligand_smiles")
    if isinstance(smiles, str) and smiles.strip():
        return smiles.strip()
    ligand = merged.get("ligand")
    if isinstance(ligand, dict):
        if ligand.get("smiles"):
            return str(ligand["smiles"]).strip()
        ligand = ligand.get("ccd") or ligand.get("ccdCode")
    if isinstance(ligand, str) and ligand.strip():
        value = ligand.strip()
        if value.upper().startswith("CCD_"):
            return value.upper()
        if value.isalnum() and len(value) <= 6:
            return f"CCD_{value.upper()}"
        return value
    return None


def _build_input(merged: dict[str, Any], scratch: Path) -> tuple[Path, bool, int]:
    name, template = _protein_template(merged)
    sequences: list[dict[str, dict[str, Any]]] = [
        {"proteinChain": {"sequence": template, "count": 1}}
    ]
    ligand = _ligand_value(merged, scratch)
    if ligand:
        sequences.append({"ligand": {"ligand": ligand, "count": 1}})
    dna = str(merged.get("dnaSequence") or "").strip().upper()
    rna = str(merged.get("rnaSequence") or "").strip().upper()
    if dna:
        if set(dna) - set("ATGCN"):
            raise ValueError("dnaSequence may contain only A, T, G, C, and N")
        sequences.append({"dnaSequence": {"sequence": dna, "count": 1}})
    if rna:
        if set(rna) - set("AUGCN"):
            raise ValueError("rnaSequence may contain only A, U, G, C, and N")
        sequences.append({"rnaSequence": {"sequence": rna, "count": 1}})
    conditional = bool(ligand or dna or rna)
    input_path = scratch / "input.json"
    input_path.write_text(json.dumps([{"name": f"papercrane-{name}", "sequences": sequences}]))
    return input_path, conditional, len(template)


def _to_cif(path: Path) -> bytes:
    if path.suffix.lower() in {".cif", ".mmcif"}:
        return path.read_bytes()
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("disco", str(path))
    output = path.with_suffix(".cif")
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(str(output))
    return output.read_bytes()


def _sequence_for_seed(out_dir: Path, seed: int, structure_path: Path) -> str:
    candidates = sorted((out_dir / "sequences").glob(f"*sample_{seed}*.txt"))
    for path in candidates:
        text = path.read_text(errors="replace")
        matches = re.findall(r"[ACDEFGHIKLMNPQRSTVWY]{10,}", text.upper())
        if matches:
            return max(matches, key=len)
    from Bio.PDB import MMCIFParser, PDBParser
    from Bio.SeqUtils import seq1

    parser = MMCIFParser(QUIET=True) if structure_path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    structure = parser.get_structure("disco", str(structure_path))
    sequence = "".join(
        seq1(residue.resname, custom_map={"UNK": "X"})
        for residue in structure.get_residues()
        if residue.id[0] == " " and "CA" in residue
    )
    return sequence.replace("X", "")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/disco/{seed}.cif"
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


def _run(seeds: list[int], merged: dict[str, Any], scratch: Path) -> tuple[Path, bool, int]:
    input_path, conditional, protein_length = _build_input(merged, scratch)
    out_dir = scratch / "output"
    experiment = str(merged.get("experiment") or ("diverse" if conditional else "designable"))
    effort = str(merged.get("effort") or ("max" if conditional else "fast"))
    if experiment not in {"designable", "diverse"}:
        raise ValueError("experiment must be designable or diverse")
    if effort not in {"fast", "max"}:
        raise ValueError("effort must be fast or max")
    command = [
        DISCO_PYTHON,
        "runner/inference.py",
        f"experiment={experiment}",
        f"effort={effort}",
        f"input_json_path={input_path}",
        f"seeds=[{','.join(str(seed) for seed in seeds)}]",
        f"dump_dir={out_dir}",
        "use_deepspeed_evo_attention=false",
    ]
    if merged.get("noisyGuidance") is False:
        command.append("sample_diffusion.noisy_guidance.enabled=false")
    completed = subprocess.run(
        command,
        cwd=DISCO_DIR,
        text=True,
        capture_output=True,
        timeout=TIMEOUT_MIN * 60 - 30,
        env={**os.environ, "HF_HOME": CACHE_DIR, "TRANSFORMERS_CACHE": CACHE_DIR},
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-4000:]
        raise RuntimeError(f"DISCO exited with {completed.returncode}: {tail}")
    return out_dir, conditional, protein_length


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    memory=65536,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def papercrane_dispatch(job_id: str, seeds=None, params=None, prev_output=None) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    completed = 0
    with tempfile.TemporaryDirectory(prefix="papercrane-disco-") as tmp:
        scratch = Path(tmp)
        out_dir, conditional, requested_length = _run(seed_values, merged, scratch)
        for seed in seed_values:
            structures = sorted((out_dir / "pdbs").glob(f"*sample_{seed}*.pdb"))
            structures += sorted((out_dir / "pdbs").glob(f"*sample_{seed}*.cif"))
            if not structures:
                error_files = sorted((out_dir / "ERR").glob("*.txt"))
                detail = error_files[0].read_text(errors="replace")[-2000:] if error_files else ""
                raise RuntimeError(f"DISCO produced no structure for seed {seed}: {detail}")
            structure_path = structures[0]
            sequence = _sequence_for_seed(out_dir, seed, structure_path)
            content = _to_cif(structure_path)
            artifact_key = _upload(merged, seed, content)
            _emit({
                "type": "seed",
                "seed": seed,
                "designId": f"{job_id}-{seed}",
                "sequence": sequence or None,
                "artifactKey": artifact_key,
                "metrics": {
                    "protein_length": float(len(sequence) or requested_length),
                    "conditional": 1.0 if conditional else 0.0,
                },
            })
            completed += 1
    summary = {"tool": "disco", "completed": completed, "requested": len(seed_values)}
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "disco-smoke",
        json.dumps([0]),
        json.dumps({"proteinLength": 70, "experiment": "designable", "effort": "fast"}),
    )
