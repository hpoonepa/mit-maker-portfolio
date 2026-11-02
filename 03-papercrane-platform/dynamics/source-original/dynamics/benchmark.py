"""Recovery metrics and baseline comparison. PURE."""
from __future__ import annotations
from math import sqrt


def _dist(a, b) -> float:
    return sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def is_hit(
    predicted: tuple[float, float, float],
    ground_truth: tuple[float, float, float],
    distance_threshold: float,
) -> bool:
    return _dist(predicted, ground_truth) <= distance_threshold


def recovery_rate(per_target: list[dict], distance_threshold: float) -> float:
    if not per_target:
        return 0.0
    hits = 0
    for t in per_target:
        if any(
            is_hit(p, t["ground_truth"], distance_threshold)
            for p in t.get("predictions", [])
        ):
            hits += 1
    return hits / len(per_target)


def compare_recovery(
    ensemble_results: list[dict],
    static_results: list[dict],
    distance_threshold: float,
) -> dict:
    e_rate = recovery_rate(ensemble_results, distance_threshold)
    s_rate = recovery_rate(static_results, distance_threshold)
    return {
        "ensemble_recovery": e_rate,
        "static_recovery": s_rate,
        "margin_pp": (e_rate - s_rate) * 100.0,
        "n_targets_ensemble": len(ensemble_results),
        "n_targets_static": len(static_results),
    }
