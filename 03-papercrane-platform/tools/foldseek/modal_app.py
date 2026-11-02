# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane pairwise structure comparison with Foldseek."""

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

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))
FOLDSEEK_VERSION = "10-941cd33"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ca-certificates", "tar", "wget")
    .run_commands(
        f"wget -q https://github.com/steineggerlab/foldseek/releases/download/{FOLDSEEK_VERSION}/foldseek-linux-avx2.tar.gz -O /tmp/foldseek.tar.gz",
        "tar -xzf /tmp/foldseek.tar.gz -C /opt",
        "ln -s /opt/foldseek/bin/foldseek /usr/local/bin/foldseek",
    )
    .pip_install("biopython==1.85")
)

app = modal.App("papercrane-foldseek", image=image)


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
    request = urllib.request.Request(
        url, headers={"User-Agent": "papercrane-foldseek/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _resolve_structure(
    merged: dict[str, Any], name: str, scratch: Path, fallback: str
) -> Path:
    internal = merged.get("_papercrane")
    internal = internal if isinstance(internal, dict) else {}
    url = internal.get(f"{name}StructureUrl") or merged.get(f"{name}PdbUrl")
    if url:
        suffix = ".cif" if ".cif" in str(url).lower() else ".pdb"
        return _download(str(url), scratch / f"{name}{suffix}")
    raw = merged.get(f"{name}PdbText")
    if raw:
        suffix = ".cif" if str(raw).lstrip().startswith("data_") else ".pdb"
        path = scratch / f"{name}{suffix}"
        path.write_text(str(raw))
        return path
    ref = merged.get(f"{name}Pdb") or fallback
    candidate = Path(str(ref))
    if candidate.exists():
        return candidate
    if len(str(ref)) == 4 and str(ref).isalnum():
        return _download(
            f"https://files.rcsb.org/download/{str(ref).upper()}.cif",
            scratch / f"{name}.cif",
        )
    raise ValueError(
        f"{name}Pdb must be a 4-character PDB id, local path, or uploaded structure"
    )


def _as_cif(path: Path) -> bytes:
    if path.suffix.lower() in {".cif", ".mmcif"} and path.read_text(
        errors="ignore"
    ).lstrip().startswith("data_"):
        return path.read_bytes()
    from Bio.PDB import MMCIFIO, MMCIFParser, PDBParser

    parser = (
        MMCIFParser(QUIET=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True)
    )
    structure = parser.get_structure("query", str(path))
    output = io.StringIO()
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/foldseek/{seed}.cif"
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


def _compare(
    query: Path, target: Path, merged: dict[str, Any], scratch: Path
) -> dict[str, float]:
    output = scratch / "alignment.tsv"
    tmp_dir = scratch / "foldseek-tmp"
    fields = [
        "fident",
        "alnlen",
        "evalue",
        "bits",
        "prob",
        "alntmscore",
        "qtmscore",
        "ttmscore",
        "lddt",
    ]
    command = [
        "foldseek",
        "easy-search",
        str(query),
        str(target),
        str(output),
        str(tmp_dir),
        "--alignment-type",
        str(int(merged.get("alignmentType", 1))),
        "--format-output",
        ",".join(fields),
        "--exact-tmscore",
        "1",
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Foldseek exited with {completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}"
        )
    line = next(
        (line for line in output.read_text().splitlines() if line.strip()), None
    )
    if line is None:
        raise RuntimeError(
            "Foldseek found no alignment between the supplied structures"
        )
    values = line.split("\t")
    if len(values) != len(fields):
        raise RuntimeError(f"unexpected Foldseek output with {len(values)} columns")
    return {field: float(value) for field, value in zip(fields, values)}


@app.function(timeout=TIMEOUT_MIN * 60, cpu=4.0, memory=8192)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        with tempfile.TemporaryDirectory(prefix="papercrane-foldseek-") as tmp:
            scratch = Path(tmp)
            query = _resolve_structure(merged, "target", scratch, "1CRN")
            partner = _resolve_structure(merged, "partner", scratch, "1UBQ")
            metrics = _compare(query, partner, merged, scratch)
            content = _as_cif(query)
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
                "code": "FOLDSEEK_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "foldseek",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "foldseek-smoke",
        json.dumps([0]),
        json.dumps({"targetPdb": "1CRN", "partnerPdb": "1UBQ"}),
    )
