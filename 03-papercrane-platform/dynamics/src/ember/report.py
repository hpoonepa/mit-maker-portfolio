"""Render measured results only. Missing methods stay explicitly unrun."""

from __future__ import annotations

from .evaluate import paired_bootstrap


def markdown_report(
    results: list[dict],
    *,
    baseline_id: str,
    planned_methods: list[str] | None = None,
    bootstrap_resamples: int = 10000,
) -> str:
    if not results:
        raise ValueError("No measured prediction results to report")
    by_method = {result["method_id"]: result for result in results}
    if len(by_method) != len(results) or baseline_id not in by_method:
        raise ValueError("Unique methods and an evaluated baseline are required")
    baseline = by_method[baseline_id]
    for result in results:
        for key in ("cohort_sha256", "protocol_sha256", "reference_sha256"):
            if result[key] != baseline[key]:
                raise ValueError("Cannot put different cohorts/protocols/references on one leaderboard")
    lines = [
        "# Ember Pocket evaluation",
        "",
        "Measured predictions on one frozen cohort. "
        "This custom residue-set metric is separate from published-author protocols.",
        "",
        f"Cohort SHA-256: `{baseline['cohort_sha256']}`.",
        "",
        f"Eligible positive proteins: {baseline['n_eligible_positive_targets']}; "
        f"negative controls: {baseline['n_negative_controls']}; exclusions: {baseline['n_excluded']}.",
        "",
    ]

    def percent(value):
        return "undefined" if value is None else f"{100 * value:.1f}%"

    ceiling = baseline.get("macro_output_budget_ceiling", {}).get("3")
    if ceiling is not None:
        lines += [
            f"The three-output budget alone caps macro recall at {percent(ceiling)}; "
            "proposal coverage and duplicate-site constraints can lower the attainable value further.",
            "",
        ]
    lines += [
        "| Method | Recall@3 | Difference vs baseline (95% family interval) | Output success | Known cost |",
        "| --- | ---: | --- | ---: | ---: |",
    ]

    for method, result in sorted(by_method.items()):
        comparison = "baseline"
        if method != baseline_id:
            if result["n_eligible_positive_targets"]:
                delta = paired_bootstrap(result, baseline, resamples=bootstrap_resamples)
                interval = delta["ci95"]
                comparison = f"{100 * delta['difference']:+.1f} pp"
                comparison += (
                    f" [{100 * interval[0]:+.1f}, {100 * interval[1]:+.1f}]"
                    if interval
                    else " [not estimable]"
                )
            else:
                comparison = "undefined"
        cost = f"${result['cost_usd_known_total']:.2f}" + ("" if result["cost_complete"] else " (incomplete)")
        escaped = method.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {escaped} | {percent(result['macro_recall']['3'])} | {comparison} | {percent(result['output_success_rate'])} | {cost} |"
        )
    for method in sorted(set(planned_methods or []) - set(by_method)):
        lines.append(f"| {method.replace('|', '/')} | Not run | Not compared | — | — |")
    lines += [
        "",
        "Failures and missing eligible predictions remain misses. Successful static fallbacks are "
        "scored and flagged. Unknown cost is not treated as zero. No score here establishes binding, "
        "kinetics, equilibrium occupancy or functional modulation.",
        "",
        "## Failure accounting",
        "",
    ]
    for method, result in sorted(by_method.items()):
        counts = ", ".join(f"{key}: {value}" for key, value in sorted(result["status_counts"].items()))
        lines.append(f"- {method}: {counts}.")
    return "\n".join(lines) + "\n"
