#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""CLI for the benchmark evaluation, plus the markdown renderer.

    python scripts/run_evaluation.py \
        --manifest data/benchmark/manifest.csv \
        --arms external,external+filter,geometric,geometric+filter \
        --filter preflight --out artifacts/eval --seed 0

Writes ``<out>.md`` and ``<out>.json``. Deterministic: the same manifest, arms
and seed produce byte-identical files. Every dropped row is logged with its
reason, to stderr and into the report; there are no silent caps.

``--structure-dir`` registers both real arms (``geometric`` and ``preflight``)
over a coordinate cache. Third-party arms register themselves through
``register_predictor``/``register_filter`` and are loaded with ``--plugin``,
which is why this script runs end to end without a structure reader and
refuses to invent an arm it cannot build. Rendering lives here rather than in
``benchmark/evaluate.py`` so the statistics module has no presentation layer
to drag through its tests.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from benchmark.render import render_markdown  # noqa: E402
from benchmark.evaluate import (  # noqa: E402
    FILTER_REGISTRY,
    PREDICTOR_REGISTRY,
    Arm,
    EvaluationResult,
    FilterPolicy,
    Predictor,
    load_manifest,
    run_evaluation,
)

LOGGER = logging.getLogger("run_evaluation")


# ---------------------------------------------------------------------------
# Arm strings
# ---------------------------------------------------------------------------
def build_arms(
    specs: list[str], *, filter_name: str = "preflight"
) -> tuple[Arm, ...]:
    """Build arms from ``--arms`` strings like ``geometric+filter``.

    One predictor *object* per predictor name, because ``run_evaluation``
    pairs a filtered arm to its unfiltered arm by predictor identity.

    Raises:
        ValueError: naming every registered predictor and filter, so a typo
            is a one-line fix rather than a hunt.
    """
    arms: list[Arm] = []
    shared: dict[str, Predictor] = {}
    for spec in (s.strip() for s in specs):
        if not spec:
            continue
        base, _, suffix = spec.partition("+")
        base = base.strip()
        if base not in PREDICTOR_REGISTRY:
            raise ValueError(
                f"unknown predictor {base!r} in arm {spec!r}. Registered "
                f"predictors: {sorted(PREDICTOR_REGISTRY)}"
            )
        predictor = shared.setdefault(base, PREDICTOR_REGISTRY[base])
        if not suffix:
            arms.append(Arm(base, predictor))
            continue
        chosen = filter_name if suffix.strip() == "filter" else suffix.strip()
        if chosen not in FILTER_REGISTRY:
            raise ValueError(
                f"unknown filter {chosen!r} in arm {spec!r}. Registered "
                f"filters: {sorted(FILTER_REGISTRY)}"
            )
        arms.append(Arm(spec, predictor, FILTER_REGISTRY[chosen]))
    if not arms:
        raise ValueError("--arms resolved to zero arms")
    return tuple(arms)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_evaluation",
        description="Four-arm evaluation of the hotspot-preflight reality filter.",
    )
    parser.add_argument("--manifest", required=True, type=Path,
                        help="benchmark manifest CSV, one row per antibody instance")
    parser.add_argument("--arms", required=True,
                        help="comma-separated arms, e.g. 'external,external+filter,"
                             "geometric,geometric+filter'. '<name>+filter' adds the "
                             "filter named by --filter; '<name>+<other>' names one "
                             "explicitly.")
    parser.add_argument("--out", required=True, type=Path,
                        help="output path stem; writes <out>.md and <out>.json")
    parser.add_argument("--filter", dest="filter_name", default="preflight",
                        help="which registered filter '+filter' means (default: "
                             "preflight)")
    parser.add_argument("--limit", type=int, default=None,
                        help="evaluate at most N instances; every row cut is logged")
    parser.add_argument("--cutoff", type=float, default=4.5,
                        help="epitope contact cutoff in angstrom (default 4.5; 4.0 "
                             "is the published sensitivity analysis)")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    parser.add_argument("--n-boot", type=int, default=10000,
                        help="bootstrap resamples (default 10000)")
    parser.add_argument("--split", default=None,
                        help="restrict to one manifest split, e.g. 'test'")
    parser.add_argument("--headline-k", type=int, default=5,
                        help="patch-recall cut-off for the headline delta")
    parser.add_argument("--filter-policy", choices=[p.value for p in FilterPolicy],
                        default=FilterPolicy.DROP_PATCH.value,
                        help="how a KILL verdict affects the patch containing it")
    parser.add_argument("--micro-average", action="store_true",
                        help="OPT-IN: report the per-instance micro-average instead "
                             "of the cluster macro-average. Dominated by the "
                             "most-deposited antigens; not a statement about "
                             "generalisation.")
    parser.add_argument("--plugin", action="append", default=[], metavar="MODULE",
                        help="import MODULE before building arms so it can register "
                             "its predictors and filters; repeatable")
    parser.add_argument("--structure-dir", type=Path, default=None,
                        help="directory of downloaded coordinates. Supplying it "
                             "registers the real `preflight` filter; without it "
                             "only the built-in controls exist and no arm runs "
                             "our checks")
    parser.add_argument("--skip-burial", action="store_true",
                        help="disable check_burial in the preflight filter (the "
                             "expensive one); the arm is labelled in the report")
    parser.add_argument("--max-patches", type=int, default=400,
                        help="cap patch enumeration per antigen (default 400, "
                             "widest-exposure first); the cap is recorded in "
                             "the report, never silent")
    parser.add_argument("--anchor-mean-floor", type=float, default=None,
                        help="kill a patch whose anchor_mean falls below this. "
                             "anchor_max is never thresholded")
    parser.add_argument("--external", action="append", default=[], metavar="ARM",
                        help="declare ARM as an external state-of-the-art "
                             "baseline. Without at least one, the superiority "
                             "comparison is reported as NOT RUN rather than as "
                             "a delta of zero; repeatable")
    parser.add_argument("--list-arms", action="store_true",
                        help="print the registered predictors and filters, then exit")
    return parser


def _annotate(arm: Arm) -> Arm:
    """Copy each arm's predictor/filter ``note`` onto the arm.

    The notes carry the enumeration cap, the NMS threshold and any disabled
    check: they bound what the number means, which is the same reason
    ``resampling_unit`` is printed rather than assumed.
    """
    from dataclasses import replace

    notes = [
        getattr(obj, "note", "")
        for obj in (arm.predictor, arm.filter_fn)
        if getattr(obj, "note", "")
    ]
    return replace(arm, note="; ".join(notes)) if notes else arm


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    for module in args.plugin:
        LOGGER.info("importing plugin module %s", module)
        importlib.import_module(module)

    preflight = None
    geometric = None
    if args.structure_dir is not None:
        # One flag registers both: a user who supplies coordinates wants the
        # predictor and the filter, and having to name them separately is how
        # you end up with an empty PREDICTOR_REGISTRY and a confusing error.
        from benchmark.geometric_predictor import register_geometric
        from benchmark.preflight_filter import register_preflight

        preflight = register_preflight(
            args.structure_dir,
            run_burial=not args.skip_burial,
            anchor_mean_floor=args.anchor_mean_floor,
        )
        if "geometric" not in PREDICTOR_REGISTRY:
            geometric = register_geometric(
                args.structure_dir,
                use_assembly=not args.skip_burial,
                max_patches=args.max_patches,
            )
        LOGGER.info(
            "registered 'preflight' and 'geometric' over %s", args.structure_dir
        )

    if args.list_arms:
        print("predictors:", ", ".join(sorted(PREDICTOR_REGISTRY)) or "(none)")
        print("filters:   ", ", ".join(sorted(FILTER_REGISTRY)) or "(none)")
        return 0

    top_k = sorted({1, 3, 5, args.headline_k})
    arms = build_arms(args.arms.split(","), filter_name=args.filter_name)
    arms = tuple(_annotate(arm) for arm in arms)

    instances, dropped = load_manifest(
        args.manifest, cutoff=args.cutoff, split=args.split, limit=args.limit
    )
    if preflight is not None:
        # Drop instances with no coordinates BEFORE evaluating. Treating an
        # unreadable structure as "nothing was killed" would pull the
        # false-rejection rate towards zero, which is the one direction that
        # flatters us; every drop is logged and lands in the report.
        from benchmark.evaluate import DroppedRow

        keep = []
        for instance in instances:
            if preflight.locate(instance) is None:  # same locator as geometric
                dropped.append(DroppedRow(
                    "structures", instance.instance_id,
                    f"no coordinates in {args.structure_dir}",
                ))
            else:
                keep.append(instance)
        instances = keep
        if not instances:
            raise SystemExit(
                f"none of the manifest's instances have coordinates in "
                f"{args.structure_dir}; download them first"
            )
    for row in dropped:
        LOGGER.info("dropped %s (%s): %s", row.identifier, row.source, row.reason)
    LOGGER.info(
        "evaluating %d instances across %d clusters; %d rows dropped",
        len(instances), len({i.cluster_id for i in instances}), len(dropped),
    )

    result = run_evaluation(
        instances,
        arms=arms,
        cutoff=args.cutoff,
        top_k=top_k,
        headline_k=args.headline_k,
        policy=FilterPolicy(args.filter_policy),
        macro=not args.micro_average,
        n_boot=args.n_boot,
        seed=args.seed,
        external_arms=tuple(args.external),
    )
    # The manifest-level drops happened before run_evaluation saw the rows.
    # EvaluationResult is frozen on purpose — a report must not be editable
    # after the fact — so fold them in by rebuilding rather than mutating.
    result = replace(result, dropped=tuple(dropped) + tuple(result.dropped))

    out_md = args.out.with_suffix(".md")
    out_json = args.out.with_suffix(".json")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(result), encoding="utf-8")
    out_json.write_text(result.to_json() + "\n", encoding="utf-8")
    LOGGER.info("wrote %s and %s", out_md, out_json)

    for label, arm_obj in (("preflight filter", preflight), ("geometric", geometric)):
        if arm_obj is not None and arm_obj.stats:
            LOGGER.info("%s stats: %s", label, dict(sorted(arm_obj.stats.items())))
    if result.primary is not None:
        audit = result.primary
        print(
            f"PRIMARY  false-rejection rate on {audit.arm}: "
            f"{audit.false_rejection_rate:.4f} "
            f"[{audit.false_rejection_ci.lo:.4f}, "
            f"{audit.false_rejection_ci.hi:.4f}] "
            f"over n = {audit.n_clusters} clusters"
        )
    if result.superiority is None:
        LOGGER.warning("superiority comparison %s", result.superiority_status)
    else:
        print("SUPERIORITY  " + result.superiority.sentence())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
