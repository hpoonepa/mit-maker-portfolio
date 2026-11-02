"""Rendering an :class:`~benchmark.evaluate.EvaluationResult` as markdown.

Separate from the statistics so no presentation code is dragged through their
tests, and separate from the CLI so the report can be asserted on directly.

The ordering here is a claim, not a layout choice: the primary audit leads
because it is the question the data can answer, the strict-containment
diagnostic precedes the table holding the number it explains, and the
superiority section states in words when it did not run.
"""

from __future__ import annotations

from .evaluate import EvaluationResult
from .score import PATCH_MAX_RESIDUES

__all__ = ["render_markdown"]


def _fmt(value: float, nd: int = 4) -> str:
    """Format a metric, printing ``n/a`` for a NaN rather than ``nan``.

    An undefined metric must look undefined to a human skimming the table;
    ``nan`` reads like a bug, ``n/a`` reads like a fact.
    """
    if value is None or value != value:
        return "n/a"
    return f"{value:.{nd}f}"


def _assembly_fallback_rate(result: EvaluationResult) -> float | None:
    """Prevalence of NO_ASSEMBLY_DEFINED on the primary arm, or None.

    Surfaced separately because it bounds what the benchmark can measure at
    all, rather than describing the filter.
    """
    if result.primary is None:
        return None
    for arm in result.arms:
        if arm.arm == result.primary.arm:
            return arm.warning_prevalence.get("NO_ASSEMBLY_DEFINED")
    return None


def render_markdown(result: EvaluationResult) -> str:
    """Render the report. The headline and every drop must appear."""
    cfg = result.config
    top_k: list[int] = list(cfg["top_k"])  # type: ignore[arg-type]
    lines: list[str] = [
        "# Hotspot preflight — benchmark evaluation",
        "",
        f"- Instances evaluated: **{result.n_instances}**",
        f"- Antigen clusters (the real n): **{result.n_clusters}**",
        f"- Averaging: **{cfg['averaging']}**",
        f"- Epitope cutoff: **{cfg['cutoff']} A**",
        f"- Filter policy: **{cfg['filter_policy']}**",
        f"- Bootstrap: {cfg['n_boot']} resamples over "
        f"**{cfg.get('resampling_unit', 'antigen_cluster')}**, seed {cfg['seed']}",
        f"- Rows dropped: **{len(result.dropped)}**",
        "",
    ]
    if cfg["averaging"] != "macro_by_cluster":
        lines += [
            "> **Micro-averaging was explicitly requested.** These numbers "
            "are weighted by how often each antigen was crystallised, so they "
            "are dominated by the most-deposited antigens and are not a "
            "statement about generalisation across antigens.",
            "",
        ]

    # Primary result first, because it is the one the data can answer.
    lines += ["## Primary result — false rejection and kill-reason prevalence", ""]
    audit = result.primary
    if audit is None:
        lines += [
            "**Not computed**: no arm in this run carries a filter, so there "
            "was nothing to audit. Add a `<predictor>+filter` arm.",
            "",
        ]
    else:
        ci = audit.false_rejection_ci
        lines += [
            f"False-rejection rate on `{audit.arm}`: "
            f"**{_fmt(audit.false_rejection_rate)}** "
            f"(95% BCa CI [{_fmt(ci.lo)}, {_fmt(ci.hi)}], "
            f"n = {audit.n_clusters} antigen clusters, "
            f"{audit.n_instances} instances).",
            "",
            "This is the fraction of experimentally observed epitope residues "
            "the filter wrongly KILLs. It should sit near zero, and every "
            "false kill is a bug to triage individually rather than a cost to "
            "average away.",
            "",
        ]
        if audit.clean:
            lines += [
                "The filter killed **no** observed epitope residue anywhere in "
                "this run.",
                "",
            ]
        if audit.kill_reason_prevalence:
            lines += [
                "| kill reason | fires on (frac. of instances) | "
                "kills a real epitope residue on |",
                "|---|---|---|",
            ] + [
                f"| `{code}` | {_fmt(prevalence)} | "
                f"{_fmt(audit.false_rejection_by_reason.get(code, 0.0))} |"
                for code, prevalence in sorted(
                    audit.kill_reason_prevalence.items(),
                    key=lambda kv: (-kv[1], kv[0]),
                )
            ] + [""]
        else:
            lines += [
                "No kill reasons fired, so there is no prevalence table.",
                "",
            ]

        fallback = _assembly_fallback_rate(result)
        if fallback is not None:
            lines += [
                f"**Assembly fallback: {_fmt(fallback)}** of instances declare "
                f"no biological assembly, so burial was measured on the "
                f"isolated chain and every assembly delta there is zero by "
                f"construction.",
                "",
            ]
            if fallback > 0.5:
                lines += [
                    "> **Most of this benchmark cannot test "
                    "assembly-awareness.** On these antigens the "
                    "assembly-aware path is indistinguishable from the "
                    "isolated-chain path, so the advantage this tool is built "
                    "around is largely untestable here. That is a finding "
                    "about the benchmark's composition, not a result about the "
                    "filter, and it must not be read as either.",
                    "",
                ]

    lines += ["## Superiority over a state-of-the-art predictor", ""]
    if result.superiority is None:
        lines += [f"**{result.superiority_status}**", ""]
    else:
        lines += [
            result.superiority.sentence(),
            "",
            f"Verdict: **{result.superiority.verdict.value}**",
            "",
        ]

    # The strict-containment diagnostic, stated BEFORE the table that contains
    # the near-zero number it explains. A reader seeing 0.0250 must be able to
    # tell "the method failed" from "the metric could not fire".
    primary_arm = next(
        (a for a in result.arms if result.primary and a.arm == result.primary.arm),
        result.arms[0] if result.arms else None,
    )
    if primary_arm is not None and primary_arm.median_epitope_size:
        lines += [
            "## Can strict patch recall fire at all?",
            "",
            f"Median epitope **{primary_arm.median_epitope_size:.0f} residues**; "
            f"a patch holds at most **{PATCH_MAX_RESIDUES}**. Under "
            f"`min_coverage` 0.5 a hit needs half the epitope inside one "
            f"patch, so strict containment is **arithmetically impossible on "
            f"{_fmt(primary_arm.strict_impossible_fraction)} of instances** "
            f"regardless of the predictor.",
            "",
            "The benchmark labels *antibody* epitopes while `surface.py` sizes "
            "patches for a *minibinder* interface — an antibody epitope is "
            "roughly two patches. `patch_recall` is kept unchanged and still "
            "reported (lowering the threshold until it improved would be "
            "tuning), but read `patch_overlap`, `patch_precision`, "
            "`union_coverage` and above all **per-residue AUROC**, which is "
            "scale-free and immune to this entirely, as the predictor-quality "
            "numbers.",
            "",
        ]

    header = " | ".join(f"patch recall@{k}" for k in top_k)
    lines += [
        "## Arms",
        "",
        f"| arm | {header} | false rejection rate | AUROC | AUPRC | n clusters |",
        "|---|" + "---|" * (len(top_k) + 4),
    ]
    for arm in result.arms:
        cells = " | ".join(_fmt(arm.patch_recall[k]) for k in top_k)
        lines.append(
            f"| `{arm.arm}` | {cells} | {_fmt(arm.false_rejection_rate)} | "
            f"{_fmt(arm.auroc)} | {_fmt(arm.auprc)} | {arm.n_clusters} |"
        )
    lines.append("")

    # The scale-appropriate metrics, in their own table so they are not read as
    # variants of strict containment.
    lines += [
        "### Scale-appropriate patch metrics",
        "",
        "| arm | k | overlap (>=1 res) | precision (purity) | union coverage |",
        "|---|---|---|---|---|",
    ]
    for arm in result.arms:
        for k in top_k:
            lines.append(
                f"| `{arm.arm}` | {k} | {_fmt(arm.patch_overlap.get(k, float('nan')))} "
                f"| {_fmt(arm.patch_precision.get(k, float('nan')))} "
                f"| {_fmt(arm.union_coverage.get(k, float('nan')))} |"
            )
    lines.append("")

    # The primary filter metric is never traded off against patch recall, so a
    # non-zero false-rejection rate is called out rather than left for a
    # reader to spot in a table column.
    offenders = [
        a for a in result.arms
        if a.false_rejection_rate == a.false_rejection_rate
        and a.false_rejection_rate > 0.0
    ]
    if offenders:
        lines += [
            "> **The filter killed experimentally observed epitope residues.** "
            + "; ".join(
                f"`{a.arm}` false-rejection rate {_fmt(a.false_rejection_rate)}"
                for a in offenders
            )
            + ". Every false kill is a bug to triage individually, not a cost "
            "to average away against patch recall — see the per-instance rows "
            "in the JSON summary.",
            "",
        ]

    noted = [a for a in result.arms if a.note]
    if noted:
        lines += (
            ["### Arm notes", ""]
            + [f"- `{a.arm}`: {a.note}" for a in noted]
            + [""]
        )

    lines += [
        "## Internal filter deltas",
        "",
        "Each filtered arm against the *same* predictor without the filter. "
        "These isolate the filter's effect but are not a comparison against "
        "the state of the art, so they do not support a superiority claim.",
        "",
    ]
    lines += [
        f"- {d.sentence()} Verdict: **{d.verdict.value}**." for d in result.deltas
    ] or ["- none computed"]
    lines.append("")

    lines += ["## Rows dropped", ""]
    if result.dropped:
        lines += ["| source | identifier | reason |", "|---|---|---|"] + [
            f"| {d.source} | {d.identifier} | {d.reason} |" for d in result.dropped
        ]
    else:
        lines.append("None.")
    lines += ["", "## Pre-registered policy", "", "```", result.policy, "```", ""]
    return "\n".join(lines)
