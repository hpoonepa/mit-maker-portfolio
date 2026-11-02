# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane multiple protein-sequence alignment with MAFFT."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
MAFFT_VERSION = "7.526"
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
    .apt_install("ca-certificates", "wget")
    .run_commands(
        f"wget -q https://mafft.cbrc.jp/alignment/software/mafft_{MAFFT_VERSION}-1_amd64.deb -O /tmp/mafft.deb",
        "apt-get update",
        "apt-get install -y /tmp/mafft.deb",
    )
)

app = modal.App("papercrane-mafft", image=image)


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


def _sequence_record(value: Any, fallback_id: str) -> tuple[str, str]:
    identifier = fallback_id
    if isinstance(value, dict):
        identifier = _safe_id(value.get("id"), fallback_id)
        value = value.get("sequence")
    sequence = "".join(str(value or "").split()).upper()
    if not sequence:
        raise ValueError(f"{identifier} must not be empty")
    invalid = set(sequence) - AMINO_ACIDS
    if invalid:
        raise ValueError(
            f"{identifier} contains unsupported residues: {sorted(invalid)}"
        )
    if len(sequence) > 100_000:
        raise ValueError(f"{identifier} exceeds the 100,000-residue CPU limit")
    return identifier, sequence


def _inputs(merged: dict[str, Any]) -> list[tuple[str, str]]:
    values = merged.get("sequences")
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("MAFFT requires at least two protein sequences")
    if len(values) > 1000:
        raise ValueError("MAFFT supports at most 1,000 sequences per CPU run")
    records = [
        _sequence_record(value, f"sequence_{index + 1}")
        for index, value in enumerate(values)
    ]
    if len({identifier for identifier, _ in records}) != len(records):
        raise ValueError("MAFFT sequence identifiers must be unique")
    if sum(len(sequence) for _, sequence in records) > 2_000_000:
        raise ValueError("MAFFT input exceeds the 2,000,000-residue CPU limit")
    return records


def _write_fasta(records: list[tuple[str, str]], path: Path) -> None:
    path.write_text(
        "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in records)
    )


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    identifier: str | None = None
    chunks: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            if identifier is not None:
                records.append((identifier, "".join(chunks).upper()))
            identifier = _safe_id(line[1:].split()[0], f"sequence_{len(records) + 1}")
            chunks = []
        elif line:
            chunks.append(line)
    if identifier is not None:
        records.append((identifier, "".join(chunks).upper()))
    return records


def _align(
    records: list[tuple[str, str]], merged: dict[str, Any], scratch: Path
) -> list[tuple[str, str]]:
    input_path = scratch / "sequences.fasta"
    _write_fasta(records, input_path)
    strategy = str(merged.get("strategy") or "auto").lower()
    strategy_options = {
        "auto": ["--auto"],
        "linsi": ["--localpair", "--maxiterate", "1000"],
        "ginsi": ["--globalpair", "--maxiterate", "1000"],
        "einsi": ["--genafpair", "--maxiterate", "1000"],
        "fftns2": ["--retree", "2", "--maxiterate", "0"],
    }
    if strategy not in strategy_options:
        raise ValueError(f"unknown MAFFT strategy: {strategy}")
    command = ["mafft", "--thread", "4", *strategy_options[strategy]]
    if bool(merged.get("reorder", False)):
        command.append("--reorder")
    command.append(str(input_path))
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"MAFFT exited with {completed.returncode}: {detail}")
    alignment = _parse_fasta(completed.stdout)
    if len(alignment) != len(records):
        raise RuntimeError(
            f"MAFFT returned {len(alignment)} sequences for {len(records)} inputs"
        )
    lengths = {len(sequence) for _, sequence in alignment}
    if len(lengths) != 1:
        raise RuntimeError(
            "MAFFT returned sequences with inconsistent alignment lengths"
        )
    return alignment


def _metrics(alignment: list[tuple[str, str]]) -> dict[str, float]:
    sequences = [sequence for _, sequence in alignment]
    alignment_length = len(sequences[0])
    gap_count = sum(sequence.count("-") for sequence in sequences)
    conserved = 0
    matching_pairs = 0
    comparable_pairs = 0
    for column_index in range(alignment_length):
        residues = [sequence[column_index] for sequence in sequences]
        non_gap = [residue for residue in residues if residue != "-"]
        counts = Counter(non_gap)
        if len(non_gap) == len(sequences) and len(counts) == 1:
            conserved += 1
        matching_pairs += sum(count * (count - 1) // 2 for count in counts.values())
        comparable_pairs += len(non_gap) * (len(non_gap) - 1) // 2
    total_cells = len(sequences) * alignment_length
    return {
        "sequence_count": float(len(sequences)),
        "alignment_length": float(alignment_length),
        "conserved_columns": float(conserved),
        "variable_columns": float(alignment_length - conserved),
        "gap_fraction": gap_count / total_cells if total_cells else 0.0,
        "pairwise_identity": (
            matching_pairs / comparable_pairs if comparable_pairs else 0.0
        ),
    }


def _sequence_cif(alignment: list[tuple[str, str]]) -> bytes:
    identifier, aligned_query = alignment[0]
    sequence = aligned_query.replace("-", "")
    lines = [
        "data_papercrane_mafft",
        "_entry.id papercrane_mafft",
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
        [
            "loop_",
            "_papercrane_mafft_alignment.ordinal",
            "_papercrane_mafft_alignment.sequence_id",
            "_papercrane_mafft_alignment.aligned_sequence",
        ]
    )
    lines.extend(
        f"{index} {identifier} {aligned_sequence}"
        for index, (identifier, aligned_sequence) in enumerate(alignment, 1)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/mafft/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-mafft-") as tmp:
            records = _inputs(merged)
            alignment = _align(records, merged, Path(tmp))
            metrics = _metrics(alignment)
            content = _sequence_cif(alignment)
            query_sequence = alignment[0][1].replace("-", "")
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
                "code": "MAFFT_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "mafft",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "mafft-smoke",
        json.dumps([0]),
        json.dumps(
            {
                "sequences": [
                    {
                        "id": "ubiquitin",
                        "sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
                    },
                    {
                        "id": "ubiquitin_variant",
                        "sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGA",
                    },
                ]
            }
        ),
    )
