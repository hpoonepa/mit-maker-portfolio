# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane request-scoped protein homology search with DIAMOND."""

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
DIAMOND_VERSION = "2.2.4"
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
        f"wget -q https://github.com/bbuchfink/diamond/releases/download/v{DIAMOND_VERSION}/diamond-linux64.tar.gz -O /tmp/diamond.tar.gz",
        "tar -xzf /tmp/diamond.tar.gz -C /usr/local/bin diamond",
        "chmod 0755 /usr/local/bin/diamond",
    )
)
app = modal.App("papercrane-diamond", image=image)


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


def _inputs(merged: dict[str, Any]) -> tuple[tuple[str, str], list[tuple[str, str]]]:
    query: Any = merged.get("querySequence")
    references = merged.get("referenceSequences")
    values = merged.get("sequences")
    if query is None and isinstance(values, list) and len(values) >= 2:
        query, references = values[0], values[1:]
    if query is None or not isinstance(references, list) or not references:
        raise ValueError(
            "DIAMOND requires a query and at least one supplied reference sequence"
        )
    if len(references) > 10_000:
        raise ValueError("DIAMOND supports at most 10,000 references per CPU run")
    query_record = _record(query, "query")
    reference_records = [
        _record(value, f"reference_{index + 1}")
        for index, value in enumerate(references)
    ]
    identifiers = [
        query_record[0],
        *(identifier for identifier, _ in reference_records),
    ]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("DIAMOND sequence identifiers must be unique")
    if sum(len(sequence) for _, sequence in reference_records) > 5_000_000:
        raise ValueError("DIAMOND references exceed the 5,000,000-residue CPU limit")
    return query_record, reference_records


def _run(command: list[str]) -> None:
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"DIAMOND exited with {completed.returncode}: {detail}")


def _search(
    query: tuple[str, str],
    references: list[tuple[str, str]],
    merged: dict[str, Any],
    scratch: Path,
) -> list[dict[str, Any]]:
    query_path = scratch / "query.fasta"
    reference_path = scratch / "references.fasta"
    output_path = scratch / "hits.tsv"
    query_path.write_text(f">{query[0]}\n{query[1]}\n")
    reference_path.write_text(
        "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in references)
    )
    database_path = scratch / "references"
    _run(
        [
            "diamond",
            "makedb",
            "--in",
            str(reference_path),
            "--db",
            str(database_path),
            "--threads",
            "4",
        ]
    )
    sensitivity = str(merged.get("sensitivity") or "sensitive").lower()
    allowed = {
        "fast",
        "mid-sensitive",
        "sensitive",
        "more-sensitive",
        "very-sensitive",
        "ultra-sensitive",
    }
    if sensitivity not in allowed:
        raise ValueError(f"unknown DIAMOND sensitivity: {sensitivity}")
    evalue = float(merged.get("evalue", 0.001))
    max_hits = int(merged.get("maxHits", 50))
    if evalue <= 0 or not 1 <= max_hits <= 1000:
        raise ValueError("evalue or maxHits is outside supported bounds")
    command = [
        "diamond",
        "blastp",
        "--query",
        str(query_path),
        "--db",
        str(database_path),
        "--out",
        str(output_path),
        "--outfmt",
        "6",
        "qseqid",
        "sseqid",
        "pident",
        "length",
        "evalue",
        "bitscore",
        "qcovhsp",
        f"--{sensitivity}",
        "--evalue",
        str(evalue),
        "--max-target-seqs",
        str(max_hits),
        "--threads",
        "4",
    ]
    _run(command)
    hits: list[dict[str, Any]] = []
    if not output_path.exists():
        return hits
    for line in output_path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        hits.append(
            {
                "query": _safe_id(fields[0], "query"),
                "target": _safe_id(fields[1], "reference"),
                "identity": float(fields[2]),
                "length": float(fields[3]),
                "evalue": float(fields[4]),
                "bitscore": float(fields[5]),
                "coverage": float(fields[6]),
            }
        )
    return hits


def _metrics(hits: list[dict[str, Any]], reference_count: int) -> dict[str, float]:
    top = hits[0] if hits else {}
    return {
        "reference_count": float(reference_count),
        "hit_count": float(len(hits)),
        "top_identity_percent": float(top.get("identity", 0.0)),
        "top_alignment_length": float(top.get("length", 0.0)),
        "top_evalue": float(top.get("evalue", 0.0)),
        "top_bitscore": float(top.get("bitscore", 0.0)),
        "top_query_coverage_percent": float(top.get("coverage", 0.0)),
    }


def _sequence_cif(
    identifier: str,
    sequence: str,
    hits: list[dict[str, Any]],
    metrics: dict[str, float],
) -> bytes:
    lines = [
        "data_papercrane_diamond",
        "_entry.id papercrane_diamond",
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
            "_papercrane_diamond_hit.ordinal",
            "_papercrane_diamond_hit.target_id",
            "_papercrane_diamond_hit.identity_percent",
            "_papercrane_diamond_hit.alignment_length",
            "_papercrane_diamond_hit.e_value",
            "_papercrane_diamond_hit.bit_score",
            "_papercrane_diamond_hit.query_coverage_percent",
        ]
    )
    for index, hit in enumerate(hits, 1):
        lines.append(
            f"{index} {hit['target']} {hit['identity']:.8g} {hit['length']:.8g} "
            f"{hit['evalue']:.8g} {hit['bitscore']:.8g} {hit['coverage']:.8g}"
        )
    lines.extend(
        ["loop_", "_papercrane_diamond_metric.name", "_papercrane_diamond_metric.value"]
    )
    lines.extend(f"{name} {value:.10g}" for name, value in sorted(metrics.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/diamond/{seed}.cif"
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
        query, references = _inputs(merged)
        with tempfile.TemporaryDirectory(prefix="papercrane-diamond-") as tmp:
            hits = _search(query, references, merged, Path(tmp))
        metrics = _metrics(hits, len(references))
        content = _sequence_cif(query[0], query[1], hits, metrics)
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
                "code": "DIAMOND_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "diamond",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "diamond-smoke",
        json.dumps([0]),
        json.dumps(
            {
                "sequences": [
                    "MKTAYIAKQRQISFVKSHFSRQ",
                    "MKTAYIAKQRQISFVKSHFSRQ",
                    "GAVLILKKKGHHEAELKPLAQ",
                ]
            }
        ),
    )
