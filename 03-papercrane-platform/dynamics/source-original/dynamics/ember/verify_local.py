"""Run only non-model software contracts and write a reproducible receipt.

This excludes model_checks entirely. It does not install packages, download
weights/data, execute external detectors or provision infrastructure.
"""

from __future__ import annotations

import argparse
import ast
import io
import platform
import sys
import unittest
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .io import atomic_write_json, file_hash
from .plan import implementation_hash


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).parent
    sources = sorted(path for path in root.rglob("*.py") if "research" not in path.relative_to(root).parts)
    for source in sources:
        ast.parse(source.read_text(), filename=str(source))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root.parents[1]))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    forbidden = sorted(name for name in ("torch", "transformers", "mdtraj", "bioemu") if name in sys.modules)
    passed = result.wasSuccessful() and not forbidden
    receipt = {
        "check": "local_software_contracts",
        "status": "passed" if passed else "failed",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "implementation_sha256": implementation_hash(),
        "source_sha256": {str(path.relative_to(root)): file_hash(path) for path in sources},
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "biopython": version("biopython"),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "syntax_files_checked": len(sources),
        "model_modules_loaded": forbidden,
        "model_checks_executed": False,
        "biological_benchmark_executed": False,
        "test_log": stream.getvalue(),
    }
    atomic_write_json(args.output, receipt)
    print(f"Local contracts: {receipt['status']}; {result.testsRun} checks; model checks unrun.")
    print(f"Receipt: {args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
