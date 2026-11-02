#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Filter false-rejection rate at full n, parallel and resumable.

The primary number for the half of the tool that IS the contribution. An
observed antibody epitope is, by construction, a site something really bound, so
every epitope residue the filter KILLs is a site it would have talked a user out
of. :func:`benchmark.metrics.false_rejection_rate` is that fraction.

Runs the real ``PreflightFilter`` with ``prediction=None``, which makes the
candidate set exactly the observed epitope — the filter renders a verdict on
every residue an antibody was seen to touch, which is the only way the rate is
measurable. No ranker is involved and nothing is fitted, so the manifest's split
leak does not bear on this number.

Parallel because ``check_burial`` is SASA over an expanded biological assembly
and the single-threaded cost is tens of hours at full n. One worker per antigen,
no shared state: each writes its own JSONL line and the aggregation is a separate
pass, so a killed run resumes from what landed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

_FILTER = None


def _init(structure_dir: str, run_burial: bool) -> None:
    """Build one filter per worker process.

    Per process rather than per instance because constructing it is cheap but
    the SASA reference tables it warms are not, and per-call construction would
    throw that away on every antigen.
    """
    global _FILTER
    from benchmark.preflight_filter import PreflightFilter

    _FILTER = PreflightFilter(
        structure_dir=Path(structure_dir), run_burial=run_burial
    )


def _one(inst) -> dict:
    """Judge one instance. Never raises: a crash in one antigen must not take
    down the pool and silently shrink the denominator."""
    t0 = time.monotonic()
    try:
        out = _FILTER(inst, None)
        epitope = set(inst.epitope_residues)
        # An instance the filter could not parse judges NOTHING and would score
        # a perfect 0.0 false rejection it never earned. Recorded as an error so
        # it leaves the numerator and the denominator together. 215 of 8,241
        # instances did exactly this before the manifest's `chain:seq:icode`
        # tokens were normalised.
        if not _FILTER._candidate_keys(
            inst, None,
            known_chains={c.strip() for c in inst.antigen_chains if c.strip()},
        ):
            return {
                "id": inst.instance_id,
                "cluster": inst.cluster_id,
                "err": "no candidate keys: epitope tokens did not parse",
                "secs": round(time.monotonic() - t0, 2),
            }
        killed = sorted(set(out.killed) & epitope)
        return {
            "id": inst.instance_id,
            "cluster": inst.cluster_id,
            "pdb": inst.pdb_id,
            "n_epitope": len(epitope),
            "n_killed": len(killed),
            "killed": killed,
            "reasons": {k: list(v) for k, v in (out.reasons or {}).items()
                        if k in epitope},
            "warnings": list(out.warnings or ()),
            "secs": round(time.monotonic() - t0, 2),
        }
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        return {
            "id": inst.instance_id,
            "cluster": inst.cluster_id,
            "err": f"{type(exc).__name__}: {exc}"[:200],
            "secs": round(time.monotonic() - t0, 2),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default="data/benchmark/manifest.csv")
    ap.add_argument("--structure-dir", default=".cache/benchmark/cif")
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default=None, help="restrict to one split")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 3))
    ap.add_argument("--skip-burial", action="store_true")
    args = ap.parse_args()

    from benchmark.evaluate import load_manifest

    insts, dropped = load_manifest(Path(args.manifest), split=args.split)
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.open():
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    todo = [i for i in insts if i.instance_id not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(insts)} instances in manifest ({len(dropped)} dropped at load), "
          f"{len(done)} already done, {len(todo)} to run, "
          f"{args.workers} workers, burial={'off' if args.skip_burial else 'on'}",
          flush=True)

    t0 = time.monotonic()
    n = 0
    with out.open("a") as fh, Pool(
        args.workers, initializer=_init,
        initargs=(args.structure_dir, not args.skip_burial),
    ) as pool:
        for rec in pool.imap_unordered(_one, todo, chunksize=4):
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n += 1
            if n % 100 == 0:
                el = time.monotonic() - t0
                rate = n / el
                print(f"{n}/{len(todo)}  {el:.0f}s  {rate:.1f}/s  "
                      f"eta {(len(todo) - n) / max(rate, 1e-9) / 60:.0f} min",
                      flush=True)
    print(f"done {n} in {(time.monotonic() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
