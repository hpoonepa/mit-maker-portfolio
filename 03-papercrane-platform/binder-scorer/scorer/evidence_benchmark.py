"""Reproducible, fixed-budget evaluation of supplied scores and existing outcomes.

No training or model selection happens here. Outcomes never determine ranks,
cohort membership, or the shortlist size. Exact cutoff ties are marginalized
uniformly and accompanied by best/worst possible precision.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from scorer.evidence_audit import _object, _text, build_audit, canonical_json
from scorer.evidence_audit_cli import load_input

INPUT_VERSION = "evidence-benchmark-input.v1"
REPORT_VERSION = "evidence-benchmark-report.v1"


def _ranking_metrics(rows: list[dict], outcomes: dict, method_id: str, k: int) -> dict:
    """Metrics on a labelled cohort; expected values average uniform cutoff ties."""
    groups: dict[tuple[int, int], list[str]] = defaultdict(list)
    for row in rows:
        interval = row["rank_intervals"][method_id]
        groups[(interval["best"], interval["worst"])].append(row["id"])
    positives = sum(outcomes[r["id"]] is True for r in rows)
    hits = 0.0
    lower_hits = upper_hits = 0
    dcg = 0.0
    cutoff_tie = False
    for (best, worst), ids in groups.items():
        slots = max(0, min(worst, k) - best + 1)
        n_pos = sum(outcomes[cid] is True for cid in ids)
        hits += slots * n_pos / len(ids)
        lower_hits += max(0, slots - (len(ids) - n_pos))
        upper_hits += min(slots, n_pos)
        dcg += n_pos / len(ids) * sum(1 / math.log2(rank + 1)
                                    for rank in range(best, min(worst, k) + 1))
        cutoff_tie |= best <= k < worst
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, min(positives, k) + 1))
    return {
        "precision_at_k": hits / k,
        "precision_tie_bounds": {"lower": lower_hits / k, "upper": upper_hits / k},
        "recall_at_k": hits / positives if positives else None,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else None,
        "expected_hits": hits, "known_positives": positives, "cutoff_tie": cutoff_tie,
    }


def _paired_interval(deltas: list[float], *, seed: int, samples: int) -> dict:
    result = {"mean_delta": statistics.fmean(deltas) if deltas else None,
              "groups": len(deltas), "wins": sum(d > 0 for d in deltas),
              "ties": sum(d == 0 for d in deltas), "interval_95": None,
              "interval_status": "insufficient_groups"}
    if len(deltas) < 2:
        return result
    if len(set(deltas)) == 1:
        result["interval_95"] = {"lower": deltas[0], "upper": deltas[0]}
        result["interval_status"] = "degenerate_empirical_distribution"
        return result
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas))) for _ in range(samples))

    def quantile(p: float) -> float:
        index = (len(means) - 1) * p
        lo = math.floor(index)
        hi = math.ceil(index)
        return means[lo] + (means[hi] - means[lo]) * (index - lo)

    result["interval_95"] = {"lower": quantile(0.025), "upper": quantile(0.975)}
    result["interval_status"] = "paired_group_percentile_bootstrap"
    return result


def evaluate_benchmark(payload: dict, *, top_k: int = 10,
                       bootstrap_samples: int = 5000, seed: int = 0) -> dict:
    _object(payload, "benchmark", {
        "schema_version", "benchmark_id", "baseline_method_id", "development_groups", "campaigns",
    })
    if payload["schema_version"] != INPUT_VERSION:
        raise ValueError(f"schema_version: expected {INPUT_VERSION}")
    for key in ("benchmark_id", "baseline_method_id"):
        _text(payload[key], key)
    for name, value, minimum in (("top_k", top_k, 1), ("bootstrap_samples", bootstrap_samples, 100)):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name}: expected an integer >= {minimum}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed: expected an integer")
    development = payload["development_groups"]
    if not isinstance(development, list):
        raise ValueError("development_groups: expected an array")
    for group in development:
        _text(group, "development_groups[]")
    if len(set(development)) != len(development):
        raise ValueError("development_groups: duplicate group")
    if not isinstance(payload["campaigns"], list) or not payload["campaigns"]:
        raise ValueError("campaigns: expected a nonempty array")

    evaluated = []
    normalized_campaigns = []
    campaign_ids: set[str] = set()
    reference_methods = None
    data_kind = None
    for entry in payload["campaigns"]:
        _object(entry, "campaign", {"evaluation_group", "evidence", "outcomes"})
        group = entry["evaluation_group"]
        _text(group, "evaluation_group")
        if group in development:
            raise ValueError(f"evaluation_group {group!r} overlaps declared development groups")
        # Rank using evidence alone, before reading any outcome.
        audit = build_audit(entry["evidence"], top_k=top_k)
        cid = audit["campaign_id"]
        if cid in campaign_ids:
            raise ValueError(f"duplicate campaign_id: {cid}")
        campaign_ids.add(cid)
        if reference_methods is None:
            reference_methods = audit["methods"]
            data_kind = audit["data_kind"]
        elif canonical_json(reference_methods) != canonical_json(audit["methods"]):
            raise ValueError("method definitions differ across campaigns; version methods consistently")
        if audit["data_kind"] != data_kind:
            raise ValueError("synthetic demonstrations cannot be mixed with research campaigns")
        method_ids = [method["id"] for method in audit["methods"]]
        if payload["baseline_method_id"] not in method_ids:
            raise ValueError("baseline_method_id: not present in evidence methods")
        outcomes = _object(entry["outcomes"], "outcomes", {r["id"] for r in audit["candidates"]})
        if any(value is not None and not isinstance(value, bool) for value in outcomes.values()):
            raise ValueError("outcomes: values must be true, false, or null; unknown is not negative")

        cohort = [r for r in audit["candidates"] if r["rank_intervals"]]
        reasons = []
        if len(cohort) < top_k:
            reasons.append("common_cohort_smaller_than_fixed_k")
        if any(outcomes[r["id"]] is None for r in cohort):
            reasons.append("unknown_outcomes_in_common_cohort")
        metrics = {mid: _ranking_metrics(cohort, outcomes, mid, top_k) for mid in method_ids} if not reasons else {}
        stable = [r for r in cohort if r["status"] == "consistently_in_top_k"]
        stable_known = [r for r in stable if outcomes[r["id"]] is not None]
        stable_positive = sum(outcomes[r["id"]] is True for r in stable_known)
        evaluated.append({
            "campaign_id": cid, "evaluation_group": group, "input_sha256": audit["input_sha256"],
            "supplied_candidates": len(audit["candidates"]), "common_cohort_size": len(cohort),
            "excluded_from_cohort": len(audit["candidates"]) - len(cohort),
            "unknown_outcomes_in_cohort": sum(outcomes[r["id"]] is None for r in cohort),
            "primary_eligible": not reasons, "exclusion_reasons": reasons, "metrics": metrics,
            "agreement_diagnostic": {
                "consistently_in_top_k": len(stable), "with_known_outcomes": len(stable_known),
                "positive_outcomes": stable_positive,
                "observed_positive_fraction": stable_positive / len(stable_known) if stable_known else None,
                "note": "Descriptive outcome rate for the selected subset. Compare methods using the fixed-k endpoint; probability calibration requires separate analysis.",
            },
        })
        normalized_campaigns.append({"evaluation_group": group, "campaign_id": cid,
                                     "evidence_sha256": audit["input_sha256"], "outcomes": outcomes})

    evaluated.sort(key=lambda c: c["campaign_id"])
    groups: dict[str, list[dict]] = defaultdict(list)
    for campaign in evaluated:
        if campaign["primary_eligible"]:
            groups[campaign["evaluation_group"]].append(campaign)
    group_scores = {}
    for group, campaigns in sorted(groups.items()):
        group_scores[group] = {
            method["id"]: statistics.fmean(c["metrics"][method["id"]]["precision_at_k"] for c in campaigns)
            for method in reference_methods
        }
    baseline = payload["baseline_method_id"]
    comparisons = {}
    for method in reference_methods:
        mid = method["id"]
        deltas = [scores[mid] - scores[baseline] for scores in group_scores.values()]
        comparisons[mid] = {
            "group_macro_precision_at_k": statistics.fmean(scores[mid] for scores in group_scores.values()) if groups else None,
            "versus_baseline": _paired_interval(deltas, seed=seed, samples=bootstrap_samples),
        }
    identity = {
        "schema_version": INPUT_VERSION, "benchmark_id": payload["benchmark_id"],
        "baseline_method_id": baseline, "development_groups": sorted(development),
        "campaigns": sorted(normalized_campaigns, key=lambda c: c["campaign_id"]),
    }
    return {
        "schema_version": REPORT_VERSION, "benchmark_id": payload["benchmark_id"], "data_kind": data_kind,
        "input_sha256": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "config": {"top_k": top_k, "bootstrap_samples": bootstrap_samples, "seed": seed,
                   "baseline_method_id": baseline},
        "summary": {"supplied_campaigns": len(evaluated), "primary_campaigns": sum(c["primary_eligible"] for c in evaluated),
                    "primary_evaluation_groups": len(groups)},
        "methods": reference_methods, "campaigns": evaluated,
        "group_precision_at_k": group_scores, "comparisons": comparisons,
        "interpretation": [
            "Synthetic demonstration results are illustrative only." if data_kind == "synthetic_demo" else "Results describe supplied predictions and existing outcome labels.",
            "Primary endpoint: fixed-k precision on the same complete-evidence cohort for every method.",
            "Cutoff ties are averaged uniformly; tie bounds describe possible ordering effects. Sampling intervals are reported separately.",
            "Campaigns with fewer than k comparable candidates or unknown cohort outcomes are retained in the report but excluded from primary comparisons.",
            "Targets with zero positives remain eligible for precision; their recall and NDCG are undefined.",
            "Campaigns are averaged within declared evaluation groups, then groups receive equal weight.",
            "Bootstrap intervals resample paired group-level differences; small or nonrepresentative group sets limit inference.",
            "Declared group/development overlaps are checked. Declaration accuracy, upstream training exclusion and sequence homology require independent verification.",
            "Complete-case evaluation remains conditional on evidence availability and label ascertainment.",
            "Superiority, equivalence, power, calibration and multiple-comparison conclusions require separate prespecified analyses.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate frozen supplied rankings against existing outcome labels.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        result = evaluate_benchmark(load_input(args.input), top_k=args.top_k,
                                    bootstrap_samples=args.bootstrap_samples, seed=args.seed)
        serialized = canonical_json(result)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(serialized)
    except (OSError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(f"Evaluated {result['summary']['primary_campaigns']}/{result['summary']['supplied_campaigns']} campaigns in {result['summary']['primary_evaluation_groups']} groups.")
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
