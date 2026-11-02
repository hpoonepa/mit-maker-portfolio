# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein-sequence homology search with MMseqs2."""

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
MMSEQS_VERSION = "18-8cc5c"
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
        f"wget -q https://github.com/soedinglab/MMseqs2/releases/download/{MMSEQS_VERSION}/mmseqs-linux-avx2.tar.gz -O /tmp/mmseqs.tar.gz",
        "tar -xzf /tmp/mmseqs.tar.gz -C /opt",
        "ln -s /opt/mmseqs/bin/mmseqs /usr/local/bin/mmseqs",
    )
)

app = modal.App("papercrane-mmseqs2", image=image)


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


def _inputs(merged: dict[str, Any]) -> tuple[tuple[str, str], list[tuple[str, str]]]:
    combined = merged.get("sequences")
    combined = combined if isinstance(combined, list) else []
    query_value = merged.get("querySequence") or merged.get("sequence")
    if query_value is None and combined:
        query_value = combined[0]
    references_value = merged.get("referenceSequences") or merged.get("references")
    if references_value is None and len(combined) > 1:
        references_value = combined[1:]
    if not isinstance(references_value, list) or not references_value:
        raise ValueError("at least one reference sequence is required")
    if len(references_value) > 1000:
        raise ValueError("at most 1,000 reference sequences are supported per run")
    query = _sequence_record(query_value, "query")
    references = [
        _sequence_record(value, f"reference_{index + 1}")
        for index, value in enumerate(references_value)
    ]
    return query, references


def _write_fasta(records: list[tuple[str, str]], path: Path) -> None:
    path.write_text(
        "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in records)
    )


def _search(
    query: tuple[str, str],
    references: list[tuple[str, str]],
    merged: dict[str, Any],
    scratch: Path,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    query_path = scratch / "query.fasta"
    references_path = scratch / "references.fasta"
    output_path = scratch / "hits.tsv"
    _write_fasta([query], query_path)
    _write_fasta(references, references_path)
    fields = [
        "query",
        "target",
        "fident",
        "alnlen",
        "mismatch",
        "gapopen",
        "qstart",
        "qend",
        "tstart",
        "tend",
        "evalue",
        "bits",
    ]
    max_hits = int(merged.get("maxHits", 50))
    command = [
        "mmseqs",
        "easy-search",
        str(query_path),
        str(references_path),
        str(output_path),
        str(scratch / "mmseqs-tmp"),
        "--threads",
        "4",
        "-s",
        str(float(merged.get("sensitivity", 7.5))),
        "-e",
        str(float(merged.get("evalue", 0.001))),
        "--max-seqs",
        str(max_hits),
        "--format-output",
        ",".join(fields),
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"MMseqs2 exited with {completed.returncode}: {detail}")
    hits: list[dict[str, Any]] = []
    if output_path.exists():
        for line in output_path.read_text().splitlines():
            values = line.split("\t")
            if not line.strip() or len(values) != len(fields):
                continue
            hits.append(
                {
                    "query": _safe_id(values[0], "query"),
                    "target": _safe_id(values[1], "reference"),
                    "fident": float(values[2]),
                    "alnlen": int(values[3]),
                    "evalue": float(values[10]),
                    "bits": float(values[11]),
                }
            )
    metrics = {
        "reference_count": float(len(references)),
        "hit_count": float(len(hits)),
        "query_length": float(len(query[1])),
    }
    if hits:
        top = hits[0]
        metrics.update(
            {
                "top_sequence_identity": float(top["fident"]),
                "top_alignment_length": float(top["alnlen"]),
                "top_query_coverage": float(top["alnlen"]) / len(query[1]),
                "top_evalue": float(top["evalue"]),
                "top_bit_score": float(top["bits"]),
            }
        )
    return metrics, hits


def _sequence_cif(query: tuple[str, str], hits: list[dict[str, Any]]) -> bytes:
    identifier, sequence = query
    lines = [
        "data_papercrane_mmseqs2",
        "_entry.id papercrane_mmseqs2",
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
    if hits:
        lines.extend(
            [
                "loop_",
                "_papercrane_mmseqs2_hit.ordinal",
                "_papercrane_mmseqs2_hit.target_id",
                "_papercrane_mmseqs2_hit.fraction_identity",
                "_papercrane_mmseqs2_hit.alignment_length",
                "_papercrane_mmseqs2_hit.e_value",
                "_papercrane_mmseqs2_hit.bit_score",
            ]
        )
        lines.extend(
            f"{index} {hit['target']} {hit['fident']:.8g} {hit['alnlen']} "
            f"{hit['evalue']:.8g} {hit['bits']:.8g}"
            for index, hit in enumerate(hits, 1)
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/mmseqs2/{seed}.cif"
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
        with tempfile.TemporaryDirectory(prefix="papercrane-mmseqs2-") as tmp:
            query, references = _inputs(merged)
            metrics, hits = _search(query, references, merged, Path(tmp))
            content = _sequence_cif(query, hits)
            for seed in seed_values:
                artifact_key = _upload(merged, seed, content)
                _emit(
                    {
                        "type": "seed",
                        "seed": seed,
                        "designId": f"{job_id}-{seed}",
                        "artifactKey": artifact_key,
                        "sequence": query[1],
                        "metrics": metrics,
                    }
                )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "MMSEQS2_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "mmseqs2",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "mmseqs2-smoke",
        json.dumps([0]),
        json.dumps(
            {
                "querySequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
                "referenceSequences": [
                    {
                        "id": "ubiquitin_variant",
                        "sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGA",
                    }
                ],
            }
        ),
    )
