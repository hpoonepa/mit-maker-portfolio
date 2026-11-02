"""ToolManifest loader + validator.

Mirrors `packages/tools-sdk/src/manifest.ts`. The pydantic schema in
`types.py::ToolManifest` enforces the same rules as the zod schema on the TS
side (id regex, sha256 digest, tier/category enums, compute profile bounds).
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from .types import ToolManifest


def load_manifest(path: str | Path) -> ToolManifest:
    """Load and validate a ``manifest.json`` from disk.

    Raises ``FileNotFoundError`` if the file is missing, ``ValueError`` if the
    JSON fails schema validation, and ``json.JSONDecodeError`` on malformed
    JSON.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in manifest at {p}: {e}") from e

    try:
        return ToolManifest.model_validate(data)
    except PydanticValidationError as e:
        raise ValueError(f"Invalid manifest at {p}: {e}") from e


__all__ = ["ToolManifest", "load_manifest"]
