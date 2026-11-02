# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein profile comparison with HH-suite HHalign."""

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

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "10"))
HHSUITE_VERSION = "3.3.0"
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYXBZJUO")
THREE_LETTER = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ca-certificates", "tar", "wget")
    .run_commands(
        "mkdir -p /opt/hhsuite",
        f"wget -q https://github.com/soedinglab/hh-suite/releases/download/v{HHSUITE_VERSION}/hhsuite-{HHSUITE_VERSION}-AVX2-Linux.tar.gz -O /tmp/hhsuite.tar.gz",
        "tar -xzf /tmp/hhsuite.tar.gz -C /opt/hhsuite",
        "ln -s /opt/hhsuite/bin/hhalign /usr/local/bin/hhalign",
    )
)
app = modal.App("papercrane-hhsuite", image=image)


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


def _safe_id(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("_")
    return (cleaned or fallback)[:120]


def _record(value: Any, fallback_id: str) -> tuple[str, str]:
    identifier = fallback_id
    if isinstance(value, dict):
        identifier = _safe_id(value.get("id"), fallback_id)
        value = value.get("sequence")
    sequence = "".join(str(value or "").split()).upper()
    if len(sequence) < 6:
        raise ValueError(f"{identifier} must contain at least 6 residues")
    invalid = set(sequence) - AMINO_ACIDS
    if invalid:
        raise ValueError(
            f"{identifier} contains unsupported residues: {sorted(invalid)}"
        )
    if len(sequence) > 100_000:
        raise ValueError(f"{identifier} exceeds the 100,000-residue CPU limit")
    return identifier, sequence


def _first_alignment_sequence(text: str, label: str) -> tuple[str, str, int]:
    if len(text.encode("utf-8")) > 5_000_000:
        raise ValueError(f"{label} alignment exceeds the 5 MB CPU limit")
    identifier: str | None = None
    chunks: list[str] = []
    sequence_count = sum(
        1 for raw_line in text.splitlines() if raw_line.strip().startswith(">")
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            if identifier is None:
                identifier = _safe_id(line[1:].split()[0], label)
            elif chunks:
                break
        elif line and identifier is not None:
            chunks.append(line)
    if identifier is None or not chunks:
        raise ValueError(
            f"{label} must be an A3M/FASTA alignment with at least one record"
        )
    aligned = "".join(chunks)
    invalid = set(aligned.upper()) - AMINO_ACIDS - {"-", "."}
    if invalid:
        raise ValueError(
            f"{label} contains unsupported alignment characters: {sorted(invalid)}"
        )
    sequence = "".join(char for char in aligned if char.isupper() and char not in "-.")
    if len(sequence) < 6:
        raise ValueError(
            f"{label} master sequence must contain at least 6 match-state residues"
        )
    return identifier, sequence, sequence_count


def _inputs(merged: dict[str, Any]) -> tuple[str, str, str, str, int, int]:
    query_alignment = merged.get("queryAlignment")
    reference_alignment = merged.get("referenceAlignment")
    if query_alignment is not None or reference_alignment is not None:
        if not isinstance(query_alignment, str) or not isinstance(
            reference_alignment, str
        ):
            raise ValueError(
                "both queryAlignment and referenceAlignment are required together"
            )
        query_id, query_sequence, query_depth = _first_alignment_sequence(
            query_alignment, "query"
        )
        _, _, reference_depth = _first_alignment_sequence(
            reference_alignment, "reference"
        )
        return (
            query_id,
            query_sequence,
            query_alignment,
            reference_alignment,
            query_depth,
            reference_depth,
        )
    query: Any = merged.get("querySequence")
    reference: Any = merged.get("referenceSequence")
    values = merged.get("sequences")
    if (
        (query is None or reference is None)
        and isinstance(values, list)
        and len(values) == 2
    ):
        query, reference = values
    if query is None or reference is None:
        raise ValueError(
            "HH-suite requires query/reference sequences or two A3M alignments"
        )
    query_record = _record(query, "query")
    reference_record = _record(reference, "reference")
    return (
        query_record[0],
        query_record[1],
        f">{query_record[0]}\n{query_record[1]}\n",
        f">{reference_record[0]}\n{reference_record[1]}\n",
        1,
        1,
    )


def _compare(
    query_alignment: str,
    reference_alignment: str,
    merged: dict[str, Any],
    scratch: Path,
) -> dict[str, float]:
    query_path = scratch / "query.a3m"
    reference_path = scratch / "reference.a3m"
    output_path = scratch / "result.hhr"
    query_path.write_text(query_alignment)
    reference_path.write_text(reference_alignment)
    alignment_mode = str(merged.get("alignmentMode") or "local").lower()
    if alignment_mode not in {"local", "global"}:
        raise ValueError(f"unknown HHalign alignmentMode: {alignment_mode}")
    mact = float(merged.get("mact", 0.35))
    if not 0 <= mact < 1:
        raise ValueError("mact must be in [0, 1)")
    command = [
        "hhalign",
        "-i",
        str(query_path),
        "-t",
        str(reference_path),
        "-o",
        str(output_path),
        "-cpu",
        "4",
        "-loc" if alignment_mode == "local" else "-glob",
        "-mact",
        str(mact),
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"HHalign exited with {completed.returncode}: {detail}")
    text = output_path.read_text() if output_path.exists() else completed.stdout
    match = re.search(
        r"Probab=([0-9.]+)\s+E-value=([^\s]+)\s+Score=([^\s]+)\s+"
        r"Aligned_cols=(\d+)\s+Identities=([0-9.]+)%\s+Similarity=([^\s]+)\s+Sum_probs=([^\s]+)",
        text,
    )
    if not match:
        raise RuntimeError(
            "HHalign output did not contain a parseable alignment summary"
        )
    return {
        "probability_percent": float(match.group(1)),
        "evalue": float(match.group(2)),
        "score": float(match.group(3)),
        "aligned_columns": float(match.group(4)),
        "identity_percent": float(match.group(5)),
        "similarity": float(match.group(6)),
        "sum_probabilities": float(match.group(7)),
    }


def _sequence_cif(identifier: str, sequence: str, metrics: dict[str, float]) -> bytes:
    lines = [
        "data_papercrane_hhsuite",
        "_entry.id papercrane_hhsuite",
        "_entity.id 1",
        "_entity.type polymer",
        f"_entity.pdbx_description {identifier}",
        "_entity_poly.entity_id 1",
        "_entity_poly.type 'polypeptide(L)'",
        "_entity_poly.pdbx_seq_one_letter_code_can",
        ";",
        sequence,
        ";",
        "loop_",
        "_entity_poly_seq.entity_id",
        "_entity_poly_seq.num",
        "_entity_poly_seq.mon_id",
        "_entity_poly_seq.hetero",
    ]
    lines.extend(
        f"1 {index} {THREE_LETTER.get(residue, 'UNK')} n"
        for index, residue in enumerate(sequence, 1)
    )
    lines.extend(
        ["loop_", "_papercrane_hhsuite_metric.name", "_papercrane_hhsuite_metric.value"]
    )
    lines.extend(f"{name} {value:.10g}" for name, value in sorted(metrics.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/hhsuite/{seed}.cif"
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
        (
            query_id,
            query_sequence,
            query_a3m,
            reference_a3m,
            query_depth,
            reference_depth,
        ) = _inputs(merged)
        with tempfile.TemporaryDirectory(prefix="papercrane-hhsuite-") as tmp:
            metrics = _compare(query_a3m, reference_a3m, merged, Path(tmp))
        metrics.update(
            {
                "query_alignment_depth": float(query_depth),
                "reference_alignment_depth": float(reference_depth),
            }
        )
        content = _sequence_cif(query_id, query_sequence, metrics)
        for seed in seed_values:
            artifact_key = _upload(merged, seed, content)
            _emit(
                {
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "artifactKey": artifact_key,
                    "sequence": query_sequence,
                    "metrics": metrics,
                }
            )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "HHSUITE_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "hhsuite",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "hhsuite-smoke",
        json.dumps([0]),
        json.dumps({"sequences": ["MKTAYIAKQRQISFVKSHFSRQ", "MKTAYIAKQKQISFVKSHFSRQ"]}),
    )
