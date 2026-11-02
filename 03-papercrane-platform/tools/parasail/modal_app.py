# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane pairwise protein alignment with Parasail."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "5"))
PARASAIL_VERSION = "1.3.4"
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
    .apt_install("build-essential")
    .pip_install(f"parasail=={PARASAIL_VERSION}")
)
app = modal.App("papercrane-parasail", image=image)


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


def _inputs(merged: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str]]:
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
            "Parasail requires querySequence and referenceSequence, or two sequences"
        )
    return _record(query, "query"), _record(reference, "reference")


def _align(
    query: str, reference: str, merged: dict[str, Any]
) -> tuple[str, str, str, dict[str, float]]:
    import parasail

    mode = str(merged.get("mode") or "global").lower()
    functions = {
        "global": parasail.nw_trace_striped_16,
        "local": parasail.sw_trace_striped_16,
        "semi-global": parasail.sg_trace_striped_16,
    }
    function = functions.get(mode)
    if function is None:
        raise ValueError(f"unknown Parasail mode: {mode}")
    matrix_name = str(merged.get("matrix") or "blosum62").lower()
    matrix = getattr(parasail, matrix_name, None)
    if matrix is None or not hasattr(matrix, "matrix"):
        raise ValueError(f"unknown Parasail substitution matrix: {matrix_name}")
    gap_open = int(merged.get("gapOpen", 10))
    gap_extend = int(merged.get("gapExtend", 1))
    if not 1 <= gap_open <= 100 or not 0 <= gap_extend <= 20:
        raise ValueError("gapOpen/gapExtend are outside supported bounds")
    result = function(query, reference, gap_open, gap_extend, matrix)
    aligned_query = str(result.traceback.query)
    aligned_reference = str(result.traceback.ref)
    comparison = str(result.traceback.comp)
    columns = len(aligned_query)
    if columns == 0 or len(aligned_reference) != columns:
        raise RuntimeError("Parasail returned an empty or inconsistent alignment")
    comparable = 0
    identical = 0
    gaps = 0
    for left, right in zip(aligned_query, aligned_reference):
        if left == "-" or right == "-":
            gaps += 1
            continue
        comparable += 1
        identical += int(left == right)
    similar = comparison.count("|") + comparison.count(":")
    metrics = {
        "alignment_score": float(result.score),
        "alignment_length": float(columns),
        "aligned_residues": float(comparable),
        "identity": identical / comparable if comparable else 0.0,
        "similarity": similar / comparable if comparable else 0.0,
        "gap_fraction": gaps / columns,
        "query_coverage": sum(char != "-" for char in aligned_query) / len(query),
        "reference_coverage": sum(char != "-" for char in aligned_reference)
        / len(reference),
        "query_end": float(result.end_query),
        "reference_end": float(result.end_ref),
    }
    return aligned_query, aligned_reference, comparison, metrics


def _sequence_cif(
    identifier: str,
    sequence: str,
    aligned_query: str,
    aligned_reference: str,
    comparison: str,
    metrics: dict[str, float],
) -> bytes:
    lines = [
        "data_papercrane_parasail",
        "_entry.id papercrane_parasail",
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
            "_papercrane_parasail.query_alignment",
            ";",
            aligned_query,
            ";",
            "_papercrane_parasail.reference_alignment",
            ";",
            aligned_reference,
            ";",
            "_papercrane_parasail.comparison",
            ";",
            comparison,
            ";",
            "loop_",
            "_papercrane_parasail_metric.name",
            "_papercrane_parasail_metric.value",
        ]
    )
    lines.extend(f"{name} {value:.10g}" for name, value in sorted(metrics.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/parasail/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=2.0, memory=2048)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        (query_id, query), (_, reference) = _inputs(merged)
        aligned_query, aligned_reference, comparison, metrics = _align(
            query, reference, merged
        )
        content = _sequence_cif(
            query_id, query, aligned_query, aligned_reference, comparison, metrics
        )
        for seed in seed_values:
            artifact_key = _upload(merged, seed, content)
            _emit(
                {
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "artifactKey": artifact_key,
                    "sequence": query,
                    "metrics": metrics,
                }
            )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "PARASAIL_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "parasail",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "parasail-smoke",
        json.dumps([0]),
        json.dumps({"sequences": ["MKTAYIAKQRQISFVKSHFSRQ", "MKTAYIAKQKQISFVKSHFSRQ"]}),
    )
