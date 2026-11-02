"""Strictly assemble four independently seeded K=4 blocks into K=4/8/16 records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


_BASE_SEED = 20260904
_BLOCK_OFFSET = 1_000_000
_IDS = ("protein_id", "replica_id", "start_id", "training_seed")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSONL {path}: {exc}") from exc
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} must contain JSON objects")
    return rows


def _physical_id(row: dict[str, Any]) -> tuple[str, str, str, str]:
    try:
        values = tuple(row[name] for name in _IDS)
    except KeyError as exc:
        raise ValueError(f"record missing physical ID field {exc.args[0]}") from exc
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("physical ID values must be non-empty strings")
    return values


def _seed(row: dict[str, Any]) -> int:
    try:
        value = int(row["inference_seed"])
        paired = row["provenance"]["paired_seed"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("record lacks integer inference_seed/provenance.paired_seed") from exc
    if paired != value:
        raise ValueError("inference_seed must equal provenance.paired_seed")
    return value


def _model_provenance(row: dict[str, Any]) -> dict[str, Any]:
    try:
        provenance = dict(row["provenance"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("record lacks provenance") from exc
    provenance.pop("paired_seed", None)
    provenance.pop("augmentation", None)
    if provenance.get("samples") != 4 or provenance.get("ode_steps") != 10:
        raise ValueError("every augmentation input must be K=4 with 10 ODE steps")
    for field in ("upstream_repository", "upstream_revision", "source_checkpoint_sha256", "candidate_checkpoint_sha256"):
        if not isinstance(provenance.get(field), str) or not provenance[field]:
            raise ValueError(f"record provenance lacks {field}")
    return provenance


def _validate_arrays(row: dict[str, Any]) -> None:
    try:
        start = np.asarray(row["start"], dtype=float)
        target = np.asarray(row["target"], dtype=float)
        if start.ndim != 2 or start.shape[1:] != (3,) or target.shape != start.shape:
            raise ValueError
        raw = row["raw_coordinates"]
        if not isinstance(raw, dict):
            raise TypeError
        raw_target = np.asarray(raw["target"], dtype=float)
        if raw_target.shape != start.shape:
            raise ValueError
        if not isinstance(row.get("data_receipt"), dict):
            raise ValueError
        if (row.get("units") != "angstrom" or row.get("alignment") != "start_aligned"
                or not isinstance(row.get("evaluator"), str) or not row["evaluator"]
                or not isinstance(row.get("reproduction_status"), str) or not row["reproduction_status"]
                or isinstance(row.get("target_frame"), bool) or not isinstance(row.get("target_frame"), int)):
            raise ValueError
        draw_arrays = []
        for name in ("target", "source", "candidate"):
            _canonical(raw[name])
        for name in ("source", "candidate"):
            if not isinstance(row[name], list) or len(row[name]) != 4:
                raise ValueError
            if not isinstance(raw[name], list) or len(raw[name]) != 4:
                raise ValueError
            aligned = np.asarray(row[name], dtype=float)
            raw_draws = np.asarray(raw[name], dtype=float)
            if aligned.shape != (4, *start.shape):
                raise ValueError
            if raw_draws.shape != (4, *start.shape):
                raise ValueError
            draw_arrays.extend((aligned, raw_draws))
        if not all(np.all(np.isfinite(value)) for value in (start, target, raw_target, *draw_arrays)):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("records require start/target and exactly four aligned and raw C-alpha draws") from exc


def _same_inputs(first: dict[str, Any], other: dict[str, Any]) -> bool:
    fields = (
        "start", "target", "data_receipt", "units", "alignment", "evaluator",
        "reproduction_status", "target_frame",
    )
    return all(_canonical(first.get(field)) == _canonical(other.get(field)) for field in fields) and (
        _canonical(first["raw_coordinates"]["target"]) == _canonical(other["raw_coordinates"]["target"])
    ) and _canonical(_model_provenance(first)) == _canonical(_model_provenance(other))


def _blocks(original: list[dict[str, Any]], extra: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[int, dict[str, Any]]]:
    if len(original) != 20 or len(extra) != 60:
        raise ValueError("need exactly 20 original records and 60 extra K=4 records")
    grouped: dict[tuple[str, str, str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in original:
        _validate_arrays(row)
        key = _physical_id(row)
        if "block_id" in row or key in grouped:
            raise ValueError("original records must have unique physical IDs and no block_id")
        index = _seed(row) - _BASE_SEED
        if not 0 <= index < 20:
            raise ValueError("original record seed is outside the frozen block-0 schedule")
        grouped[key][0] = row
    indices = set()
    for row in extra:
        _validate_arrays(row)
        key = _physical_id(row)
        try:
            block_id = row["block_id"]
            augmentation = row["provenance"]["augmentation"]
        except (KeyError, TypeError) as exc:
            raise ValueError("extra records require block_id and augmentation provenance") from exc
        if (block_id not in (1, 2, 3) or augmentation.get("block_id") != block_id
                or augmentation.get("kind") != "k4_extension_for_derived_k16"):
            raise ValueError("extra record has invalid block_id")
        if key not in grouped or block_id in grouped[key]:
            raise ValueError("duplicate or unmatched extra augmentation block")
        index = _seed(grouped[key][0]) - _BASE_SEED
        expected = _BASE_SEED + index + block_id * _BLOCK_OFFSET
        if _seed(row) != expected or augmentation.get("generation_seed") != expected:
            raise ValueError("extra record does not follow the frozen augmentation seed schedule")
        if not _same_inputs(grouped[key][0], row):
            raise ValueError("augmentation block has altered coordinates, gauge, receipt, evaluator, or model provenance")
        grouped[key][block_id] = row
        indices.add(index)
    if len(grouped) != 20 or indices != set(range(20)) or any(set(blocks) != {0, 1, 2, 3} for blocks in grouped.values()):
        raise ValueError("missing augmentation blocks or incomplete frozen 20-transition schedule")
    return grouped


def _derive(blocks: dict[int, dict[str, Any]], size: int, file_hashes: dict[str, str]) -> dict[str, Any]:
    selected = list(range(size // 4))
    first = copy.deepcopy(blocks[0])
    first["inference_seed"] = f"derived-k{size}-{first['inference_seed']}"
    first["block_id"] = f"derived_k{size}"
    first["source"] = sum((blocks[index]["source"] for index in selected), [])
    first["candidate"] = sum((blocks[index]["candidate"] for index in selected), [])
    first["raw_coordinates"]["source"] = sum((blocks[index]["raw_coordinates"]["source"] for index in selected), [])
    first["raw_coordinates"]["candidate"] = sum((blocks[index]["raw_coordinates"]["candidate"] for index in selected), [])
    provenance = first["provenance"]
    provenance["paired_seed"] = None
    provenance["samples"] = size
    provenance["augmentation"] = {
        "derived_ensemble_size": size,
        "block_ids": selected,
        "input_hashes": {str(index): _digest(blocks[index]) for index in selected},
        "input_files_sha256": file_hashes,
        "blocks": [
            {"block_id": index, "generation_seed": _seed(blocks[index]),
             "record_sha256": _digest(blocks[index]), "provenance": blocks[index]["provenance"]}
            for index in selected
        ],
    }
    return first


def build_prefixes(original: list[dict[str, Any]], extra: list[dict[str, Any]], file_hashes: dict[str, str] | None = None) -> dict[int, list[dict[str, Any]]]:
    """Build one record per physical transition for K=4, K=8, and K=16."""
    grouped = _blocks(original, extra)
    hashes = {} if file_hashes is None else dict(file_hashes)
    return {size: [_derive(grouped[key], size, hashes) for key in sorted(grouped)] for size in (4, 8, 16)}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-records", type=Path, required=True)
    parser.add_argument("--extra-records", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError(f"output directory already exists: {args.output_dir}")
        original = _read(args.original_records)
        extras = [row for path in args.extra_records for row in _read(path)]
        hashes = {"original": _file_hash(args.original_records),
                  **{f"extra_{index}": _file_hash(path) for index, path in enumerate(args.extra_records)}}
        prefixes = build_prefixes(original, extras, hashes)
        args.output_dir.mkdir(parents=True)
        for size, records in prefixes.items():
            with (args.output_dir / f"k{size}.jsonl").open("x") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        return 0
    except (OSError, TypeError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
