"""Deterministic JSON and content hashes; no pickle or network access."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> bytes:
    def encode(item: Any) -> Any:
        if is_dataclass(item):
            return asdict(item)
        raise TypeError(f"Unsupported JSON value: {type(item).__name__}")

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=encode
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: str | Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(
        Path(path).read_text(), object_pairs_hook=_unique_object, parse_constant=reject_constant
    )


def atomic_write_json(path: str | Path, value: Any) -> None:
    """Replace a JSON file only after a complete, fsynced write in its directory."""
    path = Path(path)
    payload = canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_jsonl(path: str | Path) -> list[dict]:
    result = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(
                line,
                object_pairs_hook=_unique_object,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
            )
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            result.append(value)
        except ValueError as error:
            raise ValueError(f"{path}:{number}: {error}") from error
    return result


def write_jsonl(path: str | Path, records: list[dict]) -> None:
    path = Path(path)
    payload = b"".join(canonical_json(record) + b"\n" for record in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
