"""Run the retained minibinder campaign and analysis scripts.

    minibinder <stage> <job> [job arguments...]

Stages cover target inspection, sequence design, independent folding, scoring
and candidate filtering. Each job keeps its own argument parser, for example:

    minibinder design v5 --seed 42 --config config/v5_5g51_hotspots.yaml
    minibinder score rank --selftest

The dispatcher does not turn the historical scripts into a single automated
workflow. The 5G51 jobs concern DWV; 2LGV/RBX1 jobs are retained learning
campaigns. Most design/folding jobs need a GPU, upstream Mosaic, model assets
and the target input described in docs/SOURCE-GUIDE.md.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from typing import NamedTuple


class Job(NamedTuple):
    module: str
    gpu: bool
    summary: str


# stage -> job name -> Job. The order within a stage is roughly the order a
# campaign uses them in.
JOBS: dict[str, dict[str, Job]] = {
    "prepare": {
        "hotspots": Job(
            "minibinder.prepare.hotspots", False,
            "Per-residue burial and accessibility on a target assembly; how an epitope is chosen",
        ),
    },
    "design": {
        "v5": Job(
            "minibinder.design.design_v5", True,
            "Configurable single-target design driver (YAML config, one seed per invocation)",
        ),
        "5g51": Job(
            "minibinder.design.design_5g51", True,
            "DWV VP3 / 5G51 single-seed design, fixed recipe",
        ),
        "2lgv": Job(
            "minibinder.design.design_2lgv", True,
            "RBX1 / 2LGV single-seed design, fixed recipe",
        ),
        "god": Job(
            "minibinder.design.god_campaign", True,
            "Multi-seed fixed-recipe campaign driver (the 'god-mode' recipe)",
        ),
        "god-5g51": Job(
            "minibinder.design.god_5g51", True,
            "god-mode recipe pointed at 5G51 (V3 series)",
        ),
        "god-5g51-v4": Job(
            "minibinder.design.god_5g51_v4", True,
            "god-mode recipe, V4 weights and template_chain fix",
        ),
    },
    "fold": {
        "boltz2": Job(
            "minibinder.fold.validate_boltz2", True,
            "Boltz-2 refold of one sequence against one target CIF",
        ),
    },
    "score": {
        "consensus": Job(
            "minibinder.score.boltz2_consensus", True,
            "Boltz-2 + Chai-1 consensus validation with an ipSAE gate",
        ),
        "tri-consensus": Job(
            "minibinder.score.tri_consensus", True,
            "Three-model (Protenix / Boltz-2 / ESMFold) consensus scoring",
        ),
        "rank": Job(
            "minibinder.score.consensus_rank", False,
            "Rank a scored CSV; --selftest and --calibrate need no GPU",
        ),
    },
    "filter": {
        "god": Job(
            "minibinder.filter.filter_god", False,
            "Composite filter and ranking over a god-mode campaign CSV",
        ),
        "rbx1": Job(
            "minibinder.filter.filter_rbx1", False,
            "The same filter for the RBX1 / 2LGV campaign",
        ),
    },
}


def _format_listing() -> str:
    lines = []
    for stage, jobs in JOBS.items():
        lines.append(f"\n{stage}")
        width = max(len(name) for name in jobs)
        for name, job in jobs.items():
            mark = "  [gpu]" if job.gpu else "       "
            lines.append(f"  {name:<{width}}{mark}  {job.summary}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="minibinder",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--list", action="store_true", help="list every stage and job")
    parser.add_argument("stage", nargs="?", choices=sorted(JOBS))
    parser.add_argument("job", nargs="?")
    known, rest = parser.parse_known_args(argv)

    if known.list or (known.help and not known.stage) or not known.stage:
        print(__doc__)
        print("Jobs ([gpu] needs a GPU and the upstream mosaic library):")
        print(_format_listing())
        return 0 if (known.list or known.help) else 2

    jobs = JOBS[known.stage]
    if known.job is None or known.job not in jobs:
        if known.job is not None:
            print(f"minibinder: unknown job {known.job!r} for stage {known.stage!r}",
                  file=sys.stderr)
        print(f"jobs in stage {known.stage!r}: {', '.join(jobs)}", file=sys.stderr)
        return 2

    job = jobs[known.job]
    # Hand the job its own argv and let its own parser speak for it.
    sys.argv = [f"minibinder {known.stage} {known.job}", *rest]
    try:
        runpy.run_module(job.module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:  # the job called sys.exit or its parser errored
        return int(exc.code or 0)
    except ImportError as exc:
        print(f"minibinder: {known.stage} {known.job} could not be imported: {exc}",
              file=sys.stderr)
        if job.gpu:
            print("This job needs the upstream mosaic library and a GPU; see the README.",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
