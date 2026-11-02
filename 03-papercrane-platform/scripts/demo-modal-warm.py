#!/usr/bin/env python3
"""Keep demo tools' Modal containers hot (and turn them back off).

Recording a demo means the first click must not pay a cold start. This pins
`min_containers` on the functions the worker actually calls, so a container is
already running and the model is already in memory when the job arrives.

A pinned container bills for every idle second. `cool` exists so you can stop
paying the moment you finish recording -- run it.

    python3 scripts/demo-modal-warm.py warm     # pin hot, before recording
    python3 scripts/demo-modal-warm.py status   # what's pinned right now
    python3 scripts/demo-modal-warm.py cool     # unpin, stop the burn

Touches no application source: `update_autoscaler` is applied at runtime to
already-deployed functions. Deploy first with `modal deploy tools/<t>/modal_app.py`.
"""

from __future__ import annotations

import sys
import time

import modal

# (app name as deployed, function name, approx idle $/hr) -- app names are NOT
# uniform: esm2 deploys as "esm2", proteinmpnn as "papercrane-proteinmpnn".
# Check `modal app list` before adding a tool here.
TARGETS: list[tuple[str, str, float]] = [
    ("esm2", "papercrane_dispatch", 1.10),            # A10G
    ("papercrane-proteinmpnn", "papercrane_dispatch", 1.10),
]

# Long enough to survive gaps between takes without re-paying a cold start.
SCALEDOWN_WINDOW_SEC = 900


def _fn(app: str, name: str):
    return modal.Function.from_name(app, name)


def warm() -> int:
    burn = 0.0
    failed = 0
    for app, name, rate in TARGETS:
        try:
            _fn(app, name).update_autoscaler(
                min_containers=1,
                buffer_containers=1,
                scaledown_window=SCALEDOWN_WINDOW_SEC,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAILED {app}/{name}: {exc}")
            failed += 1
            continue
        burn += rate
        print(f"  hot  {app}/{name}  min=1 buffer=1 scaledown={SCALEDOWN_WINDOW_SEC}s")
    if burn:
        print(f"\nBurning ~${burn:.2f}/hr while idle. Run `cool` when you finish recording.")
    return 1 if failed else 0


def cool() -> int:
    failed = 0
    for app, name, _ in TARGETS:
        try:
            _fn(app, name).update_autoscaler(min_containers=0, buffer_containers=0)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {app}/{name}: {exc}")
            failed += 1
            continue
        print(f"  cold {app}/{name}  min=0")
    print("\nUnpinned. Existing containers drain after the scaledown window.")
    return 1 if failed else 0


def status() -> int:
    """Prove it's actually hot by timing a real round trip."""
    seq = (
        "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR"
    )
    try:
        fn = _fn("esm2", "papercrane_dispatch")
        started = time.time()
        fn.remote(
            job_id="warm-status-check",
            seeds=[1],
            params={"sequences": [{"id": "probe", "sequence": seq}], "model_size": "650M"},
        )
        elapsed = time.time() - started
    except Exception as exc:  # noqa: BLE001
        print(f"esm2 probe FAILED: {exc}")
        return 1
    verdict = "HOT" if elapsed < 30 else "COLD (still starting up)"
    print(f"esm2 round trip: {elapsed:.1f}s -> {verdict}")
    return 0


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action not in {"warm", "cool", "status"}:
        print(__doc__)
        return 2
    return {"warm": warm, "cool": cool, "status": status}[action]()


if __name__ == "__main__":
    raise SystemExit(main())
