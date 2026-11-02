# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein physicochemical analysis with Biopython ProtParam."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

import modal

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "5"))
BIOPYTHON_VERSION = "1.87"
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
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

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    f"biopython=={BIOPYTHON_VERSION}"
)
app = modal.App("papercrane-protparam", image=image)


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


def _sequence(merged: dict[str, Any], seed: int = 1) -> tuple[str, str]:
    value: Any = merged.get("sequence")
    identifier = "query"
    values = merged.get("sequences")
    if value is None and isinstance(values, list) and values:
        value = values[((seed - 1) if seed > 0 else seed) % len(values)]
    if isinstance(value, dict):
        identifier = _safe_id(value.get("id"), identifier)
        value = value.get("sequence")
    sequence = "".join(str(value or "").split()).upper()
    if not sequence:
        raise ValueError("ProtParam requires a protein sequence")
    invalid = set(sequence) - AMINO_ACIDS
    if invalid:
        raise ValueError(
            "ProtParam requires the 20 standard amino acids; unsupported residues: "
            f"{sorted(invalid)}"
        )
    if len(sequence) > 100_000:
        raise ValueError("sequence exceeds the 100,000-residue CPU limit")
    return identifier, sequence


def _analyse(sequence: str, merged: dict[str, Any]) -> dict[str, float]:
    from Bio.SeqUtils.ProtParam import ProteinAnalysis

    analysis = ProteinAnalysis(sequence)
    helix, turn, sheet = analysis.secondary_structure_fraction()
    reduced, oxidized = analysis.molar_extinction_coefficient()
    flexibility = analysis.flexibility()
    metrics = {
        "sequence_length": float(len(sequence)),
        "molecular_weight_da": float(analysis.molecular_weight()),
        "aromaticity": float(analysis.aromaticity()),
        "instability_index": float(analysis.instability_index()),
        "isoelectric_point": float(analysis.isoelectric_point()),
        "gravy": float(analysis.gravy()),
        "charge_at_ph": float(analysis.charge_at_pH(float(merged.get("pH", 7.0)))),
        "helix_fraction": float(helix),
        "turn_fraction": float(turn),
        "sheet_fraction": float(sheet),
        "extinction_reduced": float(reduced),
        "extinction_oxidized": float(oxidized),
        "mean_flexibility": (
            float(sum(flexibility) / len(flexibility)) if flexibility else 0.0
        ),
    }
    for residue, percentage in analysis.amino_acids_percent.items():
        metrics[f"fraction_{residue.lower()}"] = float(percentage) / 100.0
    return metrics


def _sequence_cif(identifier: str, sequence: str, metrics: dict[str, float]) -> bytes:
    lines = [
        "data_papercrane_protparam",
        "_entry.id papercrane_protparam",
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
        f"1 {index} {THREE_LETTER[residue]} n"
        for index, residue in enumerate(sequence, 1)
    )
    lines.extend(
        [
            "loop_",
            "_papercrane_protparam.name",
            "_papercrane_protparam.value",
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
            return f"ephemeral/protparam/{seed}.cif"
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


@app.function(timeout=TIMEOUT_MIN * 60, cpu=1.0, memory=2048)
def papercrane_dispatch(
    job_id: str, seeds=None, params=None, prev_output=None
) -> dict[str, Any]:
    del prev_output
    seed_values = [int(seed) for seed in (_json_arg(seeds, []) or [0])]
    merged = _merged_params(params)
    try:
        for seed in seed_values:
            # Deterministic analysis still needs one record per pooled seed
            # lane; choosing by seed avoids analysing sequences[0] for every
            # lane and remains correct for direct multi-seed dispatches.
            identifier, sequence = _sequence(merged, seed)
            metrics = _analyse(sequence, merged)
            content = _sequence_cif(identifier, sequence, metrics)
            artifact_key = _upload(merged, seed, content)
            _emit(
                {
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "artifactKey": artifact_key,
                    "sequence": sequence,
                    "metrics": metrics,
                }
            )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "PROTPARAM_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "protparam",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "protparam-smoke",
        json.dumps([0]),
        json.dumps({"sequence": "MKWVTFISLLLLFSSAYSRGVFRRDTHKSEIAHRFKDLGE"}),
    )
