# /// script
# requires-python = ">=3.11"
# dependencies = ["modal>=1.0"]
# ///
"""Papercrane protein sequence clustering with CD-HIT."""

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

TIMEOUT_MIN = int(os.environ.get("TIMEOUT", "15"))
CD_HIT_VERSION = "4.8.1"
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
    .apt_install("build-essential", "ca-certificates", "git")
    .run_commands(
        f"git clone --depth 1 --branch V{CD_HIT_VERSION} https://github.com/weizhongli/cdhit.git /opt/cdhit",
        "make -C /opt/cdhit -j4",
        "ln -s /opt/cdhit/cd-hit /usr/local/bin/cd-hit",
    )
)
app = modal.App("papercrane-cd-hit", image=image)


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
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or fallback)).strip("_")
    return (cleaned or fallback)[:80]


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


def _records(merged: dict[str, Any]) -> list[tuple[str, str]]:
    values = merged.get("sequences")
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("CD-HIT requires at least two protein sequences")
    if len(values) > 10_000:
        raise ValueError("CD-HIT supports at most 10,000 sequences per CPU run")
    records = [
        _record(value, f"sequence_{index + 1}") for index, value in enumerate(values)
    ]
    if len({identifier for identifier, _ in records}) != len(records):
        raise ValueError("CD-HIT sequence identifiers must be unique")
    if sum(len(sequence) for _, sequence in records) > 5_000_000:
        raise ValueError("CD-HIT input exceeds the 5,000,000-residue CPU limit")
    return records


def _word_size(identity: float) -> int:
    if identity >= 0.7:
        return 5
    if identity >= 0.6:
        return 4
    if identity >= 0.5:
        return 3
    return 2


def _cluster(
    records: list[tuple[str, str]], merged: dict[str, Any], scratch: Path
) -> list[list[tuple[str, bool, float]]]:
    identity = float(merged.get("identity", 0.9))
    coverage = float(merged.get("coverage", 0.8))
    if not 0.4 <= identity <= 1.0 or not 0.0 <= coverage <= 1.0:
        raise ValueError("identity or coverage is outside supported bounds")
    input_path = scratch / "sequences.fasta"
    input_path.write_text(
        "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in records)
    )
    output_path = scratch / "clusters"
    command = [
        "cd-hit",
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-c",
        str(identity),
        "-n",
        str(_word_size(identity)),
        "-aS",
        str(coverage),
        "-aL",
        str(coverage),
        "-g",
        "1",
        "-d",
        "0",
        "-M",
        "7000",
        "-T",
        "4",
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=TIMEOUT_MIN * 60 - 10
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"CD-HIT exited with {completed.returncode}: {detail}")
    cluster_path = Path(f"{output_path}.clstr")
    if not cluster_path.exists():
        raise RuntimeError("CD-HIT did not produce a cluster file")
    clusters: list[list[tuple[str, bool, float]]] = []
    for line in cluster_path.read_text().splitlines():
        if line.startswith(">Cluster"):
            clusters.append([])
            continue
        match = re.search(r">(.+?)\.\.\.(?:\s+at\s+([0-9.]+)%|\s+\*)", line)
        if not match or not clusters:
            continue
        identifier = _safe_id(match.group(1), "sequence")
        representative = line.rstrip().endswith("*")
        identity_value = 100.0 if representative else float(match.group(2) or 0.0)
        clusters[-1].append((identifier, representative, identity_value))
    if not clusters or sum(map(len, clusters)) != len(records):
        raise RuntimeError("CD-HIT cluster output did not match the supplied sequences")
    return clusters


def _metrics(
    records: list[tuple[str, str]], clusters: list[list[tuple[str, bool, float]]]
) -> dict[str, float]:
    sizes = [len(cluster) for cluster in clusters]
    sequence_count = len(records)
    return {
        "sequence_count": float(sequence_count),
        "cluster_count": float(len(clusters)),
        "representative_count": float(len(clusters)),
        "largest_cluster": float(max(sizes)),
        "singleton_clusters": float(sum(size == 1 for size in sizes)),
        "mean_cluster_size": sequence_count / len(clusters),
        "redundancy_fraction": 1.0 - len(clusters) / sequence_count,
    }


def _sequence_cif(
    query_id: str,
    query: str,
    clusters: list[list[tuple[str, bool, float]]],
    metrics: dict[str, float],
) -> bytes:
    lines = [
        "data_papercrane_cd_hit",
        "_entry.id papercrane_cd_hit",
        "_entity.id 1",
        "_entity.type polymer",
        f"_entity.pdbx_description {query_id}",
        "_entity_poly.entity_id 1",
        "_entity_poly.type 'polypeptide(L)'",
        "_entity_poly.pdbx_seq_one_letter_code_can",
        ";",
        query,
        ";",
        "loop_",
        "_entity_poly_seq.entity_id",
        "_entity_poly_seq.num",
        "_entity_poly_seq.mon_id",
        "_entity_poly_seq.hetero",
    ]
    lines.extend(
        f"1 {index} {THREE_LETTER.get(residue, 'UNK')} n"
        for index, residue in enumerate(query, 1)
    )
    lines.extend(
        [
            "loop_",
            "_papercrane_cd_hit_member.cluster_id",
            "_papercrane_cd_hit_member.sequence_id",
            "_papercrane_cd_hit_member.representative",
            "_papercrane_cd_hit_member.identity_percent",
        ]
    )
    for cluster_index, cluster in enumerate(clusters, 1):
        for identifier, representative, identity in cluster:
            lines.append(
                f"{cluster_index} {identifier} {'yes' if representative else 'no'} {identity:.6g}"
            )
    lines.extend(
        ["loop_", "_papercrane_cd_hit_metric.name", "_papercrane_cd_hit_metric.value"]
    )
    lines.extend(f"{name} {value:.10g}" for name, value in sorted(metrics.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(merged: dict[str, Any], seed: int, content: bytes) -> str:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/cd-hit/{seed}.cif"
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
        records = _records(merged)
        with tempfile.TemporaryDirectory(prefix="papercrane-cd-hit-") as tmp:
            clusters = _cluster(records, merged, Path(tmp))
        metrics = _metrics(records, clusters)
        content = _sequence_cif(records[0][0], records[0][1], clusters, metrics)
        for seed in seed_values:
            artifact_key = _upload(merged, seed, content)
            _emit(
                {
                    "type": "seed",
                    "seed": seed,
                    "designId": f"{job_id}-{seed}",
                    "artifactKey": artifact_key,
                    "sequence": records[0][1],
                    "metrics": metrics,
                }
            )
    except Exception as exc:
        _emit(
            {
                "type": "error",
                "code": "CD_HIT_FAILED",
                "message": str(exc),
                "retryable": False,
            }
        )
        raise
    summary = {
        "tool": "cd-hit",
        "completed": len(seed_values),
        "requested": len(seed_values),
    }
    _emit({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    papercrane_dispatch.remote(
        "cd-hit-smoke",
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
