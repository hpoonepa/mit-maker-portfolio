"""CLI entrypoint: `python -m papercrane_validator.validate`.

Reads `/inputs/designs.json`, writes `/outputs/validated.json`. Exit 0 on
success, non-zero on malformed inputs / I/O errors. Metric-level failures
are captured in the output JSON (see orchestrator._compute_metrics_for_design)
and do not fail the CLI — this matches the runtime contract documented in
docs/plans/02-tool-integration.md §3.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .orchestrator import run_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="papercrane-validator",
        description="Compute Paper Crane canonical metric suite over a set of designs.",
    )
    parser.add_argument(
        "--designs-json",
        default=os.environ.get("PC_DESIGNS_JSON", "/inputs/designs.json"),
        help="Path to the upstream-tool output manifest (default: /inputs/designs.json).",
    )
    parser.add_argument(
        "--outputs-dir",
        default=os.environ.get("PC_OUTPUTS_DIR", "/outputs"),
        help="Directory to write validated.json into (default: /outputs).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("PC_LOG_LEVEL", "INFO"),
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    try:
        return run_validation(
            designs_json=args.designs_json,
            outputs_dir=args.outputs_dir,
        )
    except Exception as e:
        logging.getLogger("papercrane_validator").exception(
            "validation run failed: %s", e
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
