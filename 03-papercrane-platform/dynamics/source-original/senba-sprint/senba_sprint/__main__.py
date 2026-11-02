"""Offline commands. This module never launches a paid remote job."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def read_json(path):
    return json.loads(Path(path).read_text())


def read_records(path):
    records = []
    with Path(path).open() as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} must contain an object")
            records.append(record)
    if not records:
        raise ValueError("No endpoint records supplied")
    return records


def emit(value, output=None):
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Existing receipts are immutable; reruns need a new output filename.
        with path.open("x") as stream:
            stream.write(serialized)
        print(str(path.resolve()))
    else:
        print(serialized, end="")


def demo_records():
    """Deliberately synthetic coordinates for code verification, never model evidence."""
    import numpy as np

    rng = np.random.default_rng(20260904)
    records = []
    for protein in range(3):
        for start_id in range(2):
            start = rng.normal(size=(5 + protein, 3))
            target = start + rng.normal(scale=0.15, size=start.shape)
            source = start + rng.normal(scale=0.3, size=(4, *start.shape))
            for training_seed in ("1", "2", "3"):
                candidate = source + rng.normal(scale=0.04, size=source.shape)
                records.append({
                    "protein_id": f"SYNTHETIC_{protein}", "replica_id": "0",
                    "start_id": str(start_id), "training_seed": training_seed,
                    "inference_seed": "100", "units": "angstrom",
                    "alignment": "start_aligned", "start": start.tolist(),
                    "target": target.tolist(), "source": source.tolist(),
                    "candidate": candidate.tolist(),
                })
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "plan"):
        item = sub.add_parser(command)
        item.add_argument("manifest", type=Path)
        item.add_argument("--output", type=Path)
    item = sub.add_parser("analyze", help="Analyze existing paired endpoint JSONL")
    item.add_argument("records", type=Path)
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--bootstrap", type=int, default=2000)
    item.add_argument("--seed", type=int, default=20260904)
    item = sub.add_parser("demo", help="Synthetic end-to-end check; not SENBA evidence")
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--bootstrap", type=int, default=200)
    args = parser.parse_args(argv)
    try:
        if args.command in ("preflight", "plan"):
            from .runner import plan_jobs, preflight, validate_manifest
            manifest = read_json(args.manifest)
            validate_manifest(manifest)
            if args.command == "preflight":
                report = preflight(manifest, base_dir=args.manifest.parent)
                emit(report, args.output)
                return 0 if report["ok"] else 2
            emit(plan_jobs(manifest, base_dir=args.manifest.parent), args.output)
            return 0
        from .metrics import analyze_records
        if args.command == "demo":
            report = analyze_records(demo_records(), n_bootstrap=args.bootstrap)
            report["evidence_status"] = "SYNTHETIC_TEST_ONLY_NOT_MODEL_RESULTS"
        else:
            report = analyze_records(read_records(args.records),
                                     n_bootstrap=args.bootstrap, random_seed=args.seed)
            report["evidence_status"] = "USER_SUPPLIED_COORDINATES_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED"
            report["input_receipt"] = {
                "path": str(args.records.resolve()),
                "sha256": hashlib.sha256(args.records.read_bytes()).hexdigest(),
            }
        emit(report, args.output)
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"senba-sprint: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
