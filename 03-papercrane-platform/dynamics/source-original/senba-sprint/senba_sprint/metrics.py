"""Validation and paired ensemble metrics for pre-aligned SENBA transitions."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import math
from typing import Any, Iterable

import numpy as np


_ID_FIELDS = (
    "protein_id",
    "replica_id",
    "start_id",
    "training_seed",
    "inference_seed",
)
_SUMMARY_METRICS = (
    "sample_mse",
    "centroid_mse",
    "ensemble_variance",
    "pairwise_rmsd",
    "population_mean_mse_estimate",
    "mean_sample_rmsd",
    "centroid_rmsd",
    "energy_score",
)
_MAX_SUBSETS = 1024


def _as_coordinates(value: Any, field: str, ndim: int) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a numeric coordinate array") from exc
    if array.ndim != ndim or array.shape[-1] != 3:
        shape = "[N, 3]" if ndim == 2 else "[K, N, 3]"
        raise ValueError(f"{field} must have shape {shape}; got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{field} contains a non-finite coordinate")
    return array


def _validate_record(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"record {index} must be an object")
    for field in _ID_FIELDS:
        if not isinstance(record.get(field), str) or not record[field]:
            raise ValueError(f"record {index}: {field} must be a non-empty string")
    if record.get("units") != "angstrom":
        raise ValueError(f"record {index}: units must be 'angstrom'")
    if record.get("alignment") != "start_aligned":
        raise ValueError(f"record {index}: alignment must be 'start_aligned'")

    start = _as_coordinates(record.get("start"), "start", 2)
    target = _as_coordinates(record.get("target"), "target", 2)
    source = _as_coordinates(record.get("source"), "source", 3)
    candidate = _as_coordinates(record.get("candidate"), "candidate", 3)
    n_atoms = start.shape[0]
    if n_atoms == 0:
        raise ValueError(f"record {index}: coordinate arrays must contain atoms")
    if target.shape != start.shape:
        raise ValueError(f"record {index}: target must have the same N as start")
    if source.shape[1:] != start.shape or candidate.shape[1:] != start.shape:
        raise ValueError(
            f"record {index}: source and candidate must have the same N as start"
        )
    if source.shape != candidate.shape:
        raise ValueError(f"record {index}: source and candidate must have the same K")
    if source.shape[0] < 2:
        raise ValueError(f"record {index}: K must be at least 2")

    return {
        **{field: record[field] for field in _ID_FIELDS},
        "start": start,
        "target": target,
        "source": source,
        "candidate": candidate,
    }


def _sensitivity_ks(k: int) -> list[int]:
    if k <= 4:
        return list(range(1, k + 1))
    values = []
    current = 1
    while current < k:
        values.append(current)
        current *= 2
    return values + [k]


def _subsets_for_k(k: int, size: int, rng: np.random.Generator) -> tuple[list[tuple[int, ...]], bool]:
    count = math.comb(k, size)
    if count <= _MAX_SUBSETS:
        return list(combinations(range(k), size)), True
    chosen: set[tuple[int, ...]] = set()
    while len(chosen) < _MAX_SUBSETS:
        indices = tuple(sorted(rng.choice(k, size=size, replace=False).tolist()))
        chosen.add(indices)
    return sorted(chosen), False


def _centroid_sensitivity(
    samples: np.ndarray,
    target: np.ndarray,
    subsets_by_k: dict[int, tuple[list[tuple[int, ...]], bool]],
) -> list[dict[str, Any]]:
    output = []
    for size, (subsets, exhaustive) in subsets_by_k.items():
        errors = []
        for subset in subsets:
            centroid = samples[np.asarray(subset)].mean(axis=0)
            errors.append(float(np.mean(np.sum((centroid - target) ** 2, axis=-1))))
        output.append(
            {
                "k": size,
                "mean_centroid_mse": float(np.mean(errors)),
                "sd_centroid_mse": float(np.std(errors)),
                "n_subsets": len(subsets),
                "exhaustive": exhaustive,
            }
        )
    return output


def _metric_bundle(
    samples: np.ndarray,
    target: np.ndarray,
    subsets_by_k: dict[int, tuple[list[tuple[int, ...]], bool]],
) -> dict[str, Any]:
    k = samples.shape[0]
    squared_errors = np.mean(np.sum((samples - target) ** 2, axis=-1), axis=1)
    centroid = samples.mean(axis=0)
    centroid_mse = float(np.mean(np.sum((centroid - target) ** 2, axis=-1)))
    ensemble_variance = float(
        np.mean(np.sum((samples - centroid) ** 2, axis=-1))
    )

    target_distances = np.sqrt(squared_errors)
    pair_distances = []
    for left, right in combinations(range(k), 2):
        pair_distances.append(
            float(np.sqrt(np.mean(np.sum((samples[left] - samples[right]) ** 2, axis=-1))))
        )
    pairwise_rmsd = float(np.mean(pair_distances))
    sample_mse = float(np.mean(squared_errors))
    return {
        "sample_mse": sample_mse,
        "centroid_mse": centroid_mse,
        "ensemble_variance": ensemble_variance,
        "population_mean_mse_estimate": float(
            centroid_mse - ensemble_variance / (k - 1)
        ),
        "mse_identity_residual": float(
            sample_mse - centroid_mse - ensemble_variance
        ),
        "mean_sample_rmsd": float(np.mean(target_distances)),
        "centroid_rmsd": float(math.sqrt(centroid_mse)),
        "energy_score": float(np.mean(target_distances) - 0.5 * pairwise_rmsd),
        "pairwise_rmsd": pairwise_rmsd,
        "centroid_sensitivity": _centroid_sensitivity(
            samples, target, subsets_by_k
        ),
    }


def _validate_experiment(records: list[dict[str, Any]]) -> None:
    seen = set()
    proteins_by_seed: dict[str, set[str]] = defaultdict(set)
    units_by_seed: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    reference_by_unit: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]] = {}
    source_by_draw: dict[tuple[str, str, str, str], np.ndarray] = {}

    for record in records:
        full_id = tuple(record[field] for field in _ID_FIELDS)
        if full_id in seen:
            raise ValueError(f"duplicate record ID tuple: {full_id}")
        seen.add(full_id)
        seed = record["training_seed"]
        unit = (record["protein_id"], record["replica_id"], record["start_id"])
        proteins_by_seed[seed].add(record["protein_id"])
        units_by_seed[seed].add(unit)
        reference = reference_by_unit.setdefault(unit, (record["start"], record["target"]))
        if not (
            np.array_equal(reference[0], record["start"])
            and np.array_equal(reference[1], record["target"])
        ):
            raise ValueError(f"inconsistent start/target coordinates for transition {unit}")

        draw = unit + (record["inference_seed"],)
        if draw in source_by_draw and not np.array_equal(source_by_draw[draw], record["source"]):
            raise ValueError(
                "source must be identical when a transition/inference ID is reused "
                f"across training seeds: {draw}"
            )
        source_by_draw.setdefault(draw, record["source"])

    seed_order = sorted(proteins_by_seed)
    expected_proteins = proteins_by_seed[seed_order[0]]
    expected_units = units_by_seed[seed_order[0]]
    for seed in seed_order[1:]:
        if proteins_by_seed[seed] != expected_proteins:
            raise ValueError("training seeds have unequal protein sets")
        if units_by_seed[seed] != expected_units:
            raise ValueError("training seeds have inconsistent transition matching")


def _aggregate_by_protein(
    transitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    draws: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    record_counts: dict[tuple[str, str], int] = defaultdict(int)
    for transition in transitions:
        ids = transition["ids"]
        key = (
            ids["training_seed"],
            ids["protein_id"],
            ids["replica_id"],
            ids["start_id"],
        )
        draws[key].append(transition)
        record_counts[key[:2]] += 1

    units_by_protein: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, repeated_draws in draws.items():
        units_by_protein[key[:2]].append(
            {
                side: {
                    metric: float(
                        np.mean([draw[side][metric] for draw in repeated_draws])
                    )
                    for metric in _SUMMARY_METRICS
                }
                for side in ("source", "candidate", "delta")
            }
        )

    output = []
    for (seed, protein), units in sorted(units_by_protein.items()):
        output.append(
            {
                "training_seed": seed,
                "protein_id": protein,
                "n_transition_units": len(units),
                "n_records": record_counts[(seed, protein)],
                **{
                    side: {
                        metric: float(
                            np.mean([unit[side][metric] for unit in units])
                        )
                        for metric in _SUMMARY_METRICS
                    }
                    for side in ("source", "candidate", "delta")
                },
            }
        )
    return output


def _seed_summaries(per_protein: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_protein:
        grouped[row["training_seed"]].append(row)
    return [
        {
            "training_seed": seed,
            "n_proteins": len(rows),
            "protein_macro_delta": {
                metric: float(np.mean([row["delta"][metric] for row in rows]))
                for metric in _SUMMARY_METRICS
            },
        }
        for seed, rows in sorted(grouped.items())
    ]


def _bootstrap(
    per_protein: list[dict[str, Any]], n_bootstrap: int, random_seed: int
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_protein:
        grouped[row["training_seed"]].append(row)
    rng = np.random.default_rng(random_seed)
    output = []
    for seed, rows in sorted(grouped.items()):
        estimates = {metric: np.empty(n_bootstrap) for metric in _SUMMARY_METRICS}
        for draw_index in range(n_bootstrap):
            sampled = rng.integers(0, len(rows), size=len(rows))
            for metric in _SUMMARY_METRICS:
                estimates[metric][draw_index] = np.mean(
                    [rows[index]["delta"][metric] for index in sampled]
                )
        output.append(
            {
                "training_seed": seed,
                "resampling_unit": "protein",
                "n_bootstrap": n_bootstrap,
                "ci_percentile": {
                    metric: {
                        "low": float(np.quantile(values, 0.025)),
                        "high": float(np.quantile(values, 0.975)),
                    }
                    for metric, values in estimates.items()
                },
            }
        )
    return output


def analyze_records(
    records: Iterable[dict[str, Any]],
    n_bootstrap: int = 2000,
    random_seed: int = 20260904,
) -> dict[str, Any]:
    """Analyze paired source/candidate ensembles without changing their coordinate gauge."""
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, int) or n_bootstrap < 1:
        raise ValueError("n_bootstrap must be a positive integer")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer")
    validated = [_validate_record(record, index) for index, record in enumerate(records)]
    if not validated:
        raise ValueError("at least one record is required")
    validated.sort(key=lambda row: tuple(row[field] for field in _ID_FIELDS))
    _validate_experiment(validated)

    sensitivity_rng = np.random.default_rng(random_seed ^ 0x5EBA)
    transitions = []
    for record in validated:
        k = record["source"].shape[0]
        subsets = {
            size: _subsets_for_k(k, size, sensitivity_rng)
            for size in _sensitivity_ks(k)
        }
        source = _metric_bundle(record["source"], record["target"], subsets)
        candidate = _metric_bundle(record["candidate"], record["target"], subsets)
        transitions.append(
            {
                "ids": {field: record[field] for field in _ID_FIELDS},
                "n_atoms": record["start"].shape[0],
                "ensemble_size": k,
                "source": source,
                "candidate": candidate,
                "delta": {
                    metric: float(candidate[metric] - source[metric])
                    for metric in _SUMMARY_METRICS
                },
            }
        )

    per_protein = _aggregate_by_protein(transitions)
    per_seed = _seed_summaries(per_protein)
    return {
        "run": {
            "n_records": len(transitions),
            "n_training_seeds": len(per_seed),
            "n_proteins": len({row["protein_id"] for row in per_protein}),
            "n_transition_units": len(
                {
                    (row["ids"]["protein_id"], row["ids"]["replica_id"], row["ids"]["start_id"])
                    for row in transitions
                }
            ),
            "n_bootstrap": n_bootstrap,
            "random_seed": random_seed,
            "primary_metric": "centroid_rmsd",
        },
        "per_transition": transitions,
        "per_protein": per_protein,
        "per_seed": per_seed,
        "bootstrap": _bootstrap(per_protein, n_bootstrap, random_seed),
        "notes": [
            "Coordinates are analyzed in the supplied start-aligned gauge; no automatic or independent alignment is performed.",
            "All reported deltas are candidate minus source; negative is better for errors and energy score. Spread changes (ensemble_variance, pairwise_rmsd) have no inherently favorable sign.",
            "centroid_rmsd is the preserved primary metric; mean_sample_rmsd and population_mean_mse_estimate are finite-ensemble diagnostics.",
            "MSE is not a proper distribution score, and four samples cannot establish diversity retention.",
            "energy_score is exploratory and its unbiased interpretation assumes independent ensemble draws.",
            "Centroid sensitivity describes finite-K sampling sensitivity and does not identify an optimal K.",
            "Protein-bootstrap intervals are per training seed, exploratory with small protein counts, and conditional on supplied transitions and any upstream validation-based selection.",
            "Three evaluated training seeds do not establish precise population-level training-run uncertainty.",
            "Rescoring a supplied transition lag does not establish transfer to other lags.",
            "No hierarchical training-seed bootstrap or population-level claim is made.",
        ],
    }
