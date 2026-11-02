"""Reference-only evaluation. Inference modules must not import this module."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from .candidates import jaccard, ranked_unique
from .io import content_hash
from .schema import Prediction, Reference, Target, require_indices, unique_ids


@dataclass(frozen=True)
class EvaluationConfig:
    top_ks: tuple[int, ...] = (1, 3, 5)
    match_jaccard: float = 0.25
    dedup_jaccard: float = 0.5
    primary_k: int = 3

    def __post_init__(self) -> None:
        if not self.top_ks or any(type(k) is not int or k < 1 for k in self.top_ks):
            raise ValueError("top_ks must contain positive integers")
        if len(set(self.top_ks)) != len(self.top_ks) or self.primary_k not in self.top_ks:
            raise ValueError("Unique top_ks including primary_k required")
        if not 0 < self.match_jaccard <= 1 or not 0 < self.dedup_jaccard <= 1:
            raise ValueError("Jaccard thresholds must be in (0, 1]")


def maximum_matching(predicted, reference, threshold: float) -> list[tuple[int, int]]:
    """Maximum-cardinality bipartite assignment using augmenting paths.

    A greedy highest-overlap choice can miss a second match; this routine allows
    reassignment. Deterministic order prioritizes overlap, then reference index.
    Empty sets never count as matches.
    """
    if not 0 < threshold <= 1:
        raise ValueError("Matching threshold must be in (0, 1]")
    edges = [
        sorted(
            [j for j, truth in enumerate(reference) if jaccard(site, truth) >= threshold],
            key=lambda j: (-jaccard(site, reference[j]), j),
        )
        for site in predicted
    ]
    owners: dict[int, int] = {}

    def augment(index: int, visited: set[int]) -> bool:
        for ref_index in edges[index]:
            if ref_index in visited:
                continue
            visited.add(ref_index)
            if ref_index not in owners or augment(owners[ref_index], visited):
                owners[ref_index] = index
                return True
        return False

    for index in range(len(predicted)):
        augment(index, set())
    return sorted((pred, ref) for ref, pred in owners.items())


def average_precision(labels: list[int], scores: list[float], mask: list[bool] | None = None) -> float | None:
    """Threshold-grouped AP (ties grouped); undefined without positive labels.

    Matches non-interpolated sklearn average_precision_score for binary labels
    with positives, rather than a tie-order-dependent rank average or trapezoid.
    """
    if len(labels) != len(scores) or (mask is not None and len(mask) != len(labels)):
        raise ValueError("AP inputs must have equal lengths")
    if any(type(x) is not int or x not in (0, 1) for x in labels):
        raise ValueError("AP requires binary integer labels")
    if any(not math.isfinite(s) for s in scores):
        raise ValueError("AP scores must be finite")
    if mask is not None and any(type(x) is not bool for x in mask):
        raise ValueError("AP mask must be boolean")
    pairs = [(s, y) for i, (s, y) in enumerate(zip(scores, labels)) if mask is None or mask[i]]
    positives = sum(y for _, y in pairs)
    if positives == 0:
        return None
    groups = defaultdict(list)
    for score, label in pairs:
        groups[score].append(label)
    seen = tp = 0
    result = 0.0
    for score in sorted(groups, reverse=True):
        added = sum(groups[score])
        tp += added
        seen += len(groups[score])
        result += (added / positives) * (tp / seen)
    return result


def evaluate_method(
    targets: list[Target],
    references: list[Reference],
    predictions: list[Prediction],
    method_id: str,
    config: EvaluationConfig = EvaluationConfig(),
) -> dict:
    """All eligible reference-valid targets stay in the denominator.

    Missing references are protocol errors; missing predictions are failures.
    Zero-site references are negative controls with a separate reporting bucket,
    never assigned an artificial recall of 1. No reference-invalid record may be
    silently excluded from a frozen eligible cohort.
    """
    unique_ids(targets, "target_id")
    unique_ids(references, "target_id")
    unique_ids(predictions, "target_id")
    target_map = {t.target_id: t for t in targets}
    refs = {r.target_id: r for r in references}
    preds = {p.target_id: p for p in predictions}
    if set(preds) - set(target_map) or set(refs) - set(target_map):
        raise ValueError("Prediction/reference IDs outside the frozen cohort")
    if any(p.method_id != method_id for p in predictions):
        raise ValueError("Mixed method IDs in method evaluation")
    if len({p.method_sha256 for p in predictions}) > 1:
        raise ValueError("Mixed model/protocol versions in one method evaluation")
    rows = []
    excluded = []
    negatives = []
    for target in sorted(targets, key=lambda t: t.target_id):
        if not target.eligible:
            excluded.append({"target_id": target.target_id, "reason": target.exclusion_reason})
            continue
        reference = refs.get(target.target_id)
        if reference is None or not reference.valid:
            raise ValueError(f"Eligible target {target.target_id} lacks a valid frozen reference")
        for site in reference.sites:
            require_indices(site.residues, "reference residues", len(target.sequence))
        prediction = preds.get(target.target_id)
        if prediction is not None:
            if prediction.input_sha256 != content_hash(target):
                raise ValueError(f"Input hash mismatch for {target.target_id}")
            for site in prediction.sites:
                require_indices(site.residues, "prediction residues", len(target.sequence))
        status = prediction.status if prediction else "missing_prediction"
        scored = list(prediction.sites) if prediction else []
        row = {
            "target_id": target.target_id,
            "group_id": target.group_id,
            "status": status,
            "n_reference_sites": len(reference.sites),
            "failure_reason": prediction.failure_reason if prediction else "No prediction record",
            "runtime_seconds": prediction.runtime_seconds if prediction else None,
            "cost_usd": prediction.cost_usd if prediction else None,
            "metrics": {},
        }
        for k in config.top_ks:
            shortlist = ranked_unique(scored, top_k=k, dedup_jaccard=config.dedup_jaccard)
            matches = maximum_matching(
                [s.residues for s in shortlist], [s.residues for s in reference.sites], config.match_jaccard
            )
            row["metrics"][str(k)] = {
                "matched": len(matches),
                "n_predictions": len(shortlist),
                "recall": len(matches) / len(reference.sites) if reference.sites else None,
                "output_budget_ceiling": min(k, len(reference.sites)) / len(reference.sites)
                if reference.sites
                else None,
                "matches": [
                    {
                        "predicted_site_id": shortlist[i].site_id,
                        "reference_site_id": reference.sites[j].site_id,
                        "jaccard": jaccard(shortlist[i].residues, reference.sites[j].residues),
                    }
                    for i, j in matches
                ],
                "site_sizes": [len(s.residues) for s in shortlist],
            }
        (rows if reference.sites else negatives).append(row)
    all_eligible = rows + negatives
    known_costs = [r["cost_usd"] for r in all_eligible if r["cost_usd"] is not None]
    return {
        "schema_version": "1",
        "method_id": method_id,
        "cohort_sha256": content_hash([target_map[k] for k in sorted(target_map)]),
        "reference_sha256": content_hash(sorted(references, key=lambda x: x.target_id)),
        "protocol_sha256": content_hash(config),
        "n_eligible_positive_targets": len(rows),
        "n_negative_controls": len(negatives),
        "n_excluded": len(excluded),
        "macro_recall": {
            str(k): sum(r["metrics"][str(k)]["recall"] for r in rows) / len(rows) if rows else None
            for k in config.top_ks
        },
        "macro_output_budget_ceiling": {
            str(k): sum(r["metrics"][str(k)]["output_budget_ceiling"] for r in rows) / len(rows)
            if rows
            else None
            for k in config.top_ks
        },
        "status_counts": dict(Counter(r["status"] for r in all_eligible)),
        "output_success_rate": sum(
            r["status"] in {"ok", "static_fallback", "no_candidates"} for r in all_eligible
        )
        / len(all_eligible)
        if all_eligible
        else None,
        "cost_usd_known_total": sum(known_costs),
        "cost_complete": len(known_costs) == len(all_eligible),
        "per_target": rows,
        "negative_controls": negatives,
        "excluded": excluded,
        "metric_note": "Custom residue-set recall; not an official-author protocol reproduction.",
    }


def candidate_coverage(candidates, reference: Reference, threshold: float = 0.25) -> dict:
    matches = maximum_matching(
        [s.residues for s in candidates], [s.residues for s in reference.sites], threshold
    )
    return {
        "n_candidates": len(candidates),
        "matched": len(matches),
        "recall": len(matches) / len(reference.sites) if reference.sites else None,
    }


def _quantile(values: list[float], probability: float) -> float:
    values = sorted(values)
    position = (len(values) - 1) * probability
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def paired_bootstrap(
    left: dict, right: dict, *, k: int = 3, resamples: int = 10000, seed: int = 1729
) -> dict:
    """Resample families, preserving all proteins of each sampled family.

    The estimand remains macro-protein recall, not equal-family recall. Families
    are dependence clusters. This interval omits model-selection uncertainty.
    """
    for field in ("cohort_sha256", "reference_sha256", "protocol_sha256"):
        if left[field] != right[field]:
            raise ValueError(f"Paired comparison requires identical {field}")
    if type(resamples) is not int or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    a = {r["target_id"]: r for r in left["per_target"]}
    b = {r["target_id"]: r for r in right["per_target"]}
    if set(a) != set(b) or not a:
        raise ValueError("Identical nonempty positive cohorts required")
    groups = defaultdict(list)
    for target_id in sorted(a):
        if a[target_id]["group_id"] != b[target_id]["group_id"]:
            raise ValueError("Group assignments differ")
        difference = a[target_id]["metrics"][str(k)]["recall"] - b[target_id]["metrics"][str(k)]["recall"]
        groups[a[target_id]["group_id"]].append(difference)
    keys = sorted(groups)
    point = sum(sum(v) for v in groups.values()) / len(a)
    if len(keys) < 2:
        return {
            "difference": point,
            "ci95": None,
            "n_groups": len(keys),
            "note": "Too few independent groups to estimate uncertainty.",
        }
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        values = [value for key in rng.choices(keys, k=len(keys)) for value in groups[key]]
        draws.append(sum(values) / len(values))
    return {
        "difference": point,
        "ci95": [_quantile(draws, 0.025), _quantile(draws, 0.975)],
        "n_groups": len(keys),
        "n_targets": len(a),
        "resamples": resamples,
        "seed": seed,
        "note": "Paired family-cluster percentile interval; model-selection uncertainty excluded.",
    }
