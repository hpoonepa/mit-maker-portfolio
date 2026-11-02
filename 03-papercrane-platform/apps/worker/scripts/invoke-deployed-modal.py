#!/usr/bin/env python3
"""Invoke an already-deployed Modal function and relay its event result as NDJSON."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
import signal
import subprocess
import sys
from typing import Any

import modal


active_call: Any = None


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, separators=(",", ":")), flush=True)


def cancel_active_call(_signum: int, _frame: Any) -> None:
    if active_call is not None:
        try:
            active_call.cancel(terminate_containers=True)
        except Exception:
            pass
    raise SystemExit(130)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--environment")
    parser.add_argument("--source-app", required=True)
    parser.add_argument("--returns-events", action="store_true")
    # These two are accepted for deterministic shell-fixture tests. Production
    # payloads arrive only over stdin so signed storage URLs never hit argv.
    parser.add_argument("--job-id")
    parser.add_argument("--seeds")
    args = parser.parse_args()

    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {
        "job_id": args.job_id,
        "seeds": json.loads(args.seeds or "[]"),
        "params": {},
        "prev_output": None,
    }

    def spawn_deployed() -> Any:
        function = modal.Function.from_name(
            args.app_name,
            args.function_name,
            environment_name=args.environment,
        )
        return function.spawn(
            payload["job_id"],
            payload["seeds"],
            payload.get("params") or {},
            payload.get("prev_output"),
        )

    global active_call
    output_context = nullcontext() if args.returns_events else modal.enable_output()
    with output_context:
        try:
            active_call = spawn_deployed()
        except Exception as exc:
            message = str(exc).lower()
            missing = any(token in message for token in ("not found", "not deployed", "no function"))
            auto_deploy = (
                str(os.environ.get("PAPERCRANE_MODAL_AUTO_DEPLOY", "1"))
                .strip()
                .lower()
                not in ("0", "false", "no")
            )
            if not missing or not auto_deploy:
                raise
            deploy_args = ["modal", "deploy", args.source_app]
            if args.environment:
                deploy_args.extend(["--env", args.environment])
            subprocess.run(deploy_args, check=True)
            active_call = spawn_deployed()

        emit({"type": "call", "callId": active_call.object_id})
        result = active_call.get()

    if args.returns_events and (
        not isinstance(result, dict) or not isinstance(result.get("events"), list)
    ):
        emit({
            "type": "error",
            "code": "INVALID_OUTPUT",
            "message": "deployed function did not return an events array",
            "retryable": False,
        })
        return 2

    if isinstance(result, dict) and isinstance(result.get("events"), list):
        for event in result["events"]:
            if isinstance(event, dict):
                emit(event)
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cancel_active_call)
    signal.signal(signal.SIGINT, cancel_active_call)
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        message = str(exc)[:500]
        retryable = any(
            token in message.lower()
            for token in ("timeout", "temporar", "unavailable", "connection", "rate limit")
        )
        emit({
            "type": "error",
            "code": "PROVIDER_UNAVAILABLE" if retryable else "RUNTIME_ERROR",
            "message": message,
            "retryable": retryable,
        })
        raise
