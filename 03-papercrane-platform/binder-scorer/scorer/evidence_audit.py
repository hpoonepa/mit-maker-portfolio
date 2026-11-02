"""Audit supplied candidate rankings without fitting or inventing a scoring model.

Ranks are compared only on the common observed cohort. Rank envelopes describe
variation across supplied methods. Confidence calibration requires separate evaluation.
This module is standard-library-only and performs no I/O.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from itertools import combinations
from typing import Any

INPUT_VERSION = "evidence-audit-input.v1"
REPORT_VERSION = "evidence-audit-report.v1"
OBSERVATION_STATUSES = {"observed", "missing", "failed", "not_applicable"}
PROVENANCES = {"recorded", "unknown", "synthetic"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _object(value: Any, path: str, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing:
        raise ValueError(f"{path}: missing fields {sorted(missing)}")
    if extra:
        raise ValueError(f"{path}: unknown fields {sorted(extra)}")
    return value


def _text(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: expected a nonempty string")


def validate_input(payload: Any) -> dict:
    """Validate a strict, versioned, fully attributed evidence bundle."""
    data = _object(payload, "input", {
        "schema_version", "campaign_id", "data_kind", "methods", "candidates",
    })
    if data["schema_version"] != INPUT_VERSION:
        raise ValueError(f"schema_version: expected {INPUT_VERSION}")
    _text(data["campaign_id"], "campaign_id")
    if data["data_kind"] not in ("research", "synthetic_demo"):
        raise ValueError("data_kind: expected research or synthetic_demo")
    if not isinstance(data["methods"], list) or not data["methods"]:
        raise ValueError("methods: expected a nonempty array")
    if not isinstance(data["candidates"], list) or not data["candidates"]:
        raise ValueError("candidates: expected a nonempty array")

    method_ids: set[str] = set()
    for index, method in enumerate(data["methods"]):
        path = f"methods[{index}]"
        _object(method, path, {
            "id", "producer", "version", "evidence_family", "higher_is_better", "units", "settings",
        })
        for key in ("id", "producer", "version", "evidence_family", "units"):
            _text(method[key], f"{path}.{key}")
        if method["id"] in method_ids:
            raise ValueError(f"{path}: duplicate method id {method['id']}")
        method_ids.add(method["id"])
        if not isinstance(method["higher_is_better"], bool):
            raise ValueError(f"{path}.higher_is_better: expected a boolean")
        if not isinstance(method["settings"], dict):
            raise ValueError(f"{path}.settings: expected an object")

    candidate_ids: set[str] = set()
    for index, candidate in enumerate(data["candidates"]):
        path = f"candidates[{index}]"
        _object(candidate, path, {"id", "origin", "provenance", "scores"})
        for key in ("id", "origin", "provenance"):
            _text(candidate[key], f"{path}.{key}")
        if candidate["id"] in candidate_ids:
            raise ValueError(f"{path}: duplicate candidate id {candidate['id']}")
        candidate_ids.add(candidate["id"])
        if candidate["provenance"] not in PROVENANCES:
            raise ValueError(f"{path}.provenance: expected one of {sorted(PROVENANCES)}")
        scores = _object(candidate["scores"], f"{path}.scores", method_ids)
        for method_id, observation in scores.items():
            opath = f"{path}.scores.{method_id}"
            _object(observation, opath, {"status"}, {"value", "reason"})
            status = observation["status"]
            if not isinstance(status, str) or status not in OBSERVATION_STATUSES:
                raise ValueError(f"{opath}.status: expected one of {sorted(OBSERVATION_STATUSES)}")
            if status == "observed":
                value = observation.get("value")
                if isinstance(value, bool) or not isinstance(value, (float, int)):
                    raise ValueError(f"{opath}.value: observed scores require a finite number")
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError(f"{opath}.value: observed scores require a finite number")
            else:
                if "value" in observation:
                    raise ValueError(f"{opath}: unobserved scores must not contain a value")
                _text(observation.get("reason"), f"{opath}.reason")
            if "reason" in observation:
                _text(observation["reason"], f"{opath}.reason")
    # Also reject non-JSON settings and nonfinite numbers nested in metadata.
    try:
        canonical_json(data)
    except (ValueError, TypeError) as exc:
        raise ValueError("input: metadata must contain finite JSON values") from exc
    return data


def _rank_intervals(candidates: list[dict], method: dict) -> dict[str, dict]:
    """Retain the full occupied rank range of exact ties, without ID tie-breaking."""
    method_id = method["id"]
    ordered = sorted(candidates, key=lambda c: c["scores"][method_id]["value"],
                     reverse=method["higher_is_better"])
    ranks: dict[str, dict] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        value = ordered[start]["scores"][method_id]["value"]
        while end < len(ordered) and ordered[end]["scores"][method_id]["value"] == value:
            end += 1
        for candidate in ordered[start:end]:
            ranks[candidate["id"]] = {"best": start + 1, "worst": end}
        start = end
    return ranks


def build_audit(payload: Any, *, top_k: int = 10) -> dict:
    """Compare complete, attributed evidence without issuing biological predictions."""
    data = validate_input(payload)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k: expected a positive integer")
    methods = sorted(data["methods"], key=lambda method: method["id"])
    candidates = sorted(data["candidates"], key=lambda candidate: candidate["id"])
    families = sorted({method["evidence_family"] for method in methods})
    demo = data["data_kind"] == "synthetic_demo"

    def provenance_allowed(candidate: dict) -> bool:
        return candidate["provenance"] == "recorded" or (demo and candidate["provenance"] == "synthetic")

    cohort = [c for c in candidates if provenance_allowed(c) and
              all(o["status"] == "observed" for o in c["scores"].values())]
    effective_k = min(top_k, len(cohort))
    ranks = {method["id"]: _rank_intervals(cohort, method) for method in methods}
    comparable = {c["id"] for c in cohort}
    warnings: list[str] = []
    if demo:
        warnings.append("Synthetic demonstration: all numerical results are illustrative.")
    if len(cohort) < len(candidates):
        warnings.append("Rank comparisons cover only the common complete-evidence cohort; excluded candidates are not ranked lower.")
    if len(families) < 2:
        warnings.append("Fewer than two declared evidence families: cross-family agreement cannot be assessed.")
    if len(families) < len(methods):
        warnings.append("Some methods share an evidence family and may share errors.")
    if len(cohort) <= top_k:
        warnings.append("The common cohort does not exceed top_k; this cutoff cannot distinguish a smaller shortlist.")

    rows = []
    for candidate in candidates:
        observed = sum(o["status"] == "observed" for o in candidate["scores"].values())
        blocked = []
        if not provenance_allowed(candidate):
            blocked.append("unverified_provenance")
        if observed < len(methods):
            blocked.append("incomplete_evidence")
        intervals = {m["id"]: ranks[m["id"]][candidate["id"]] for m in methods} if candidate["id"] in comparable else {}
        envelope = None
        family_memberships = {}
        if intervals:
            envelope = {"best": min(r["best"] for r in intervals.values()),
                        "worst": max(r["worst"] for r in intervals.values())}
            for family in families:
                family_ranks = [intervals[m["id"]] for m in methods if m["evidence_family"] == family]
                family_memberships[family] = {
                    "definitely_in_top_k": all(r["worst"] <= effective_k for r in family_ranks),
                    "possibly_in_top_k": any(r["best"] <= effective_k for r in family_ranks),
                }
        if blocked:
            status = "not_comparable"
        elif len(families) < 2:
            status = "insufficient_comparison"
        elif envelope["worst"] <= effective_k:
            status = "consistently_in_top_k"
        elif envelope["best"] > effective_k:
            status = "consistently_outside_top_k"
        else:
            status = "boundary_ambiguous"
        rows.append({
            "id": candidate["id"], "origin": candidate["origin"],
            "provenance": candidate["provenance"], "status": status,
            "blocked_reasons": blocked, "observed_methods": observed,
            "total_methods": len(methods), "evidence_completeness": observed / len(methods),
            "scores": candidate["scores"], "rank_intervals": intervals,
            "rank_envelope": envelope, "family_memberships": family_memberships,
        })

    # Pairwise top-k sets are only asserted when no exact tie crosses the cutoff.
    agreements = []
    for left, right in combinations(methods, 2):
        left_ranks, right_ranks = ranks[left["id"]], ranks[right["id"]]
        ambiguous = any(r["best"] <= effective_k < r["worst"]
                        for rs in (left_ranks, right_ranks) for r in rs.values())
        left_set = {cid for cid, r in left_ranks.items() if r["worst"] <= effective_k}
        right_set = {cid for cid, r in right_ranks.items() if r["worst"] <= effective_k}
        union = left_set | right_set
        agreements.append({
            "left": left["id"], "right": right["id"],
            "same_evidence_family": left["evidence_family"] == right["evidence_family"],
            "top_k_jaccard": len(left_set & right_set) / len(union) if union and not ambiguous else None,
            "unavailable_reason": "cutoff_tie" if ambiguous else ("empty_cohort" if not union else None),
        })

    # Sort collection fields before hashing: input record order has no scientific meaning.
    normalized_input = {**data, "methods": methods, "candidates": candidates}
    coverage_by_origin = []
    for origin in sorted({c["origin"] for c in candidates}):
        group = [c for c in candidates if c["origin"] == origin]
        coverage_by_origin.append({
            "origin": origin, "total_candidates": len(group),
            "comparable_candidates": sum(c["id"] in comparable for c in group),
            "observation_counts": {
                method["id"]: {status: sum(c["scores"][method["id"]]["status"] == status for c in group)
                               for status in sorted(OBSERVATION_STATUSES)}
                for method in methods
            },
        })
    return {
        "schema_version": REPORT_VERSION,
        "input_sha256": hashlib.sha256(canonical_json(normalized_input).encode()).hexdigest(),
        "campaign_id": data["campaign_id"], "data_kind": data["data_kind"],
        "config": {"top_k": top_k, "effective_top_k": effective_k},
        "summary": {"total_candidates": len(candidates), "comparable_candidates": len(cohort),
                    "excluded_candidates": len(candidates) - len(cohort),
                    "declared_evidence_families": len(families),
                    "status_counts": dict(sorted(Counter(r["status"] for r in rows).items()))},
        "methods": methods, "candidates": rows, "method_agreement": agreements,
        "coverage_by_origin": coverage_by_origin,
        "warnings": warnings,
        "interpretation": [
            "This report audits supplied computational rankings. Binding-probability calibration requires outcome data.",
            "Rank envelopes describe best-to-worst positions across methods, including exact ties. Statistical confidence intervals require separate estimation.",
            "Evidence completeness measures the observed fraction of declared methods.",
            "Agreement can reflect shared errors. Evidence families are supplied metadata; method independence requires separate verification.",
            "Provenance records the supplied attribution; execution verification remains separate.",
            "Rank positions apply only to the named common cohort and can change when that cohort changes.",
            "The audit compares supplied scores directly, retaining explicit missingness and exact ties.",
        ],
    }
