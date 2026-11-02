"""Filesystem I/O helpers for adapter CLIs.

Centralizes the wire-format conventions so the TypeScript orchestrator and
every Python tool container agree byte-for-byte on what `/inputs/request.json`
and `/outputs/result.json` look like.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .types import DesignRequest, DesignResult, ValidationError


def read_request(path: str | Path) -> DesignRequest:
    """Parse ``/inputs/request.json`` into a validated `DesignRequest`."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return DesignRequest.model_validate(data)


def write_result(path: str | Path, result: DesignResult | dict[str, Any]) -> None:
    """Write a `DesignResult` (or an equivalent dict) as camelCase JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(result, DesignResult):
        payload: Any = result.model_dump(by_alias=True, exclude_none=True)
    else:
        payload = result
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_errors(path: str | Path, errors: Iterable[ValidationError]) -> None:
    """Write `errors.json` in the shape `{ "errors": [...] }`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"errors": [e.model_dump() for e in errors]}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def stage_outputs(outdir: str | Path) -> Path:
    """Ensure the output directory exists and return it as a `Path`."""
    p = Path(outdir)
    p.mkdir(parents=True, exist_ok=True)
    return p


__all__ = ["read_request", "write_result", "write_errors", "stage_outputs"]
