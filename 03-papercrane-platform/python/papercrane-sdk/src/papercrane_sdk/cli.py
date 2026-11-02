"""`run_cli` — one-liner entrypoint tool containers call from their run.sh.

Parses ``--request /inputs/request.json``, ``--target /inputs/target.pdb``,
``--output /outputs``, invokes the adapter lifecycle, and writes either
``/outputs/result.json`` on success or ``/outputs/errors.json`` on validation
failure (exit code 2 in that case, mirroring the BindCraft stub).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence, Type

from .adapter import Adapter
from .io import read_request, stage_outputs, write_errors, write_result
from .types import DesignResult


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper Crane tool adapter entrypoint")
    parser.add_argument("--request", required=True, help="Path to /inputs/request.json")
    parser.add_argument("--target", required=True, help="Path to /inputs/target.pdb")
    parser.add_argument("--output", required=True, help="Output directory (will be created)")
    return parser


def run_cli(adapter_cls: Type[Adapter], argv: Optional[Sequence[str]] = None) -> int:
    """Run the adapter lifecycle from CLI args.

    Returns:
        0 on success, 2 on validation failure. Other exceptions propagate.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    out_dir = stage_outputs(args.output)
    request = read_request(args.request)

    adapter = adapter_cls()

    errors = adapter.validate(request)
    if errors:
        write_errors(out_dir / "errors.json", errors)
        return 2

    workdir = out_dir / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    job = adapter.prepare(request, workdir)
    raw = adapter.run(job)
    result = adapter.parse(raw)

    if not isinstance(result, DesignResult):
        # Allow adapters to return dicts — coerce through pydantic so we catch
        # shape mistakes early at the SDK boundary, not in the orchestrator.
        result = DesignResult.model_validate(result)

    write_result(out_dir / "result.json", result)
    return 0


__all__ = ["run_cli"]
