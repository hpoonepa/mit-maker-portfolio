"""Arithmetic audit of the published full-transition comparison receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


RECEIPT_PATH = Path("receipts/full-transition-comparison.json")
BOOTSTRAP_SEED = 20260825
BOOTSTRAP_RESAMPLES = 100_000
PROTEIN_COUNT = 28
SCALAR_TOLERANCE = 1e-12
CI_TOLERANCE = 1e-6
CENTROID = "ensemble_mean_rmsd_improvement_vs_source_angstrom"
SINGLE_SAMPLE = "single_sample_rmsd_improvement_vs_source_angstrom"
PERSISTENCE = "ensemble_mean_improvement_vs_persistence_angstrom"
SOURCE_CI = "ensemble_mean_improvement_vs_source_95ci_angstrom"
PERSISTENCE_CI = "ensemble_mean_improvement_vs_persistence_95ci_angstrom"
SUMMARY_ALIAS = "ensemble_mean_improvement_vs_source_angstrom"


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return value


def _comparison(receipt: Any) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if not isinstance(receipt, dict) or not isinstance(receipt.get("comparison"), dict):
        raise ValueError("receipt must contain a comparison object")
    comparison = receipt["comparison"]
    rows = comparison.get("per_protein")
    if not isinstance(rows, list) or not rows:
        raise ValueError("comparison.per_protein must be a non-empty array")
    expected_count = comparison.get("proteins")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int):
        raise ValueError("comparison.proteins must be an integer")
    if expected_count != len(rows):
        raise ValueError("comparison.proteins does not match per_protein length")
    if expected_count != PROTEIN_COUNT:
        raise ValueError(f"full-transition receipt must contain {PROTEIN_COUNT} proteins")

    row_keys = set(rows[0])
    if "domain_id" not in row_keys or len(row_keys) < 2:
        raise ValueError("per-protein rows require domain_id and metric fields")
    metric_fields = sorted(row_keys - {"domain_id"})
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != row_keys:
            raise ValueError(f"per_protein[{index}] has missing or unexpected fields")
        domain = row["domain_id"]
        if not isinstance(domain, str) or not domain or domain in seen:
            raise ValueError(f"per_protein[{index}].domain_id must be non-empty and unique")
        seen.add(domain)
        for field in metric_fields:
            _finite_number(row[field], f"per_protein[{index}].{field}")
    for required in (CENTROID, SINGLE_SAMPLE, PERSISTENCE):
        if required not in metric_fields:
            raise ValueError(f"per-protein metric is missing: {required}")
    return comparison, rows, metric_fields


def _check(stored: Any, recomputed: float, tolerance: float) -> dict[str, Any]:
    stored_number = _finite_number(stored, "published summary")
    error = abs(stored_number - recomputed)
    return {
        "published": stored_number,
        "recomputed": recomputed,
        "absolute_error": error,
        "tolerance": tolerance,
        "matched": error <= tolerance,
    }


def _ci_check(stored: Any, recomputed: np.ndarray) -> dict[str, Any]:
    if not isinstance(stored, list) or len(stored) != 2:
        raise ValueError("published confidence interval must contain two values")
    published = [_finite_number(value, "published CI endpoint") for value in stored]
    values = [float(value) for value in recomputed]
    errors = [abs(left - right) for left, right in zip(published, values)]
    return {
        "published": published,
        "recomputed": values,
        "absolute_error": errors,
        "tolerance": CI_TOLERANCE,
        "matched": all(error <= CI_TOLERANCE for error in errors),
    }


def audit_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Recompute published summary arithmetic from retained per-protein receipts."""
    comparison, rows, metric_fields = _comparison(receipt)
    values = {
        field: np.asarray([float(row[field]) for row in rows]) for field in metric_fields
    }
    means = {field: float(array.mean()) for field, array in values.items()}
    scalar_checks = {}
    for field in metric_fields:
        if field not in comparison:
            raise ValueError(f"published comparison summary is missing: {field}")
        scalar_checks[field] = _check(comparison[field], means[field], SCALAR_TOLERANCE)
    if SUMMARY_ALIAS not in comparison:
        raise ValueError(f"published comparison summary is missing: {SUMMARY_ALIAS}")
    scalar_checks[SUMMARY_ALIAS] = _check(
        comparison[SUMMARY_ALIAS], means[CENTROID], SCALAR_TOLERANCE
    )

    count = len(rows)
    wins = {
        "centroid_vs_source": {"wins": int(np.sum(values[CENTROID] > 0)), "proteins": count},
        "single_sample_vs_source": {"wins": int(np.sum(values[SINGLE_SAMPLE] > 0)), "proteins": count},
        "centroid_vs_persistence": {"wins": int(np.sum(values[PERSISTENCE] > 0)), "proteins": count},
    }
    fraction_checks = {
        "fraction_proteins_better_than_source": _check(
            comparison.get("fraction_proteins_better_than_source"),
            wins["centroid_vs_source"]["wins"] / count,
            SCALAR_TOLERANCE,
        ),
        "fraction_proteins_better_than_persistence": _check(
            comparison.get("fraction_proteins_better_than_persistence"),
            wins["centroid_vs_persistence"]["wins"] / count,
            SCALAR_TOLERANCE,
        ),
    }

    if comparison.get("bootstrap_seed") != BOOTSTRAP_SEED:
        raise ValueError(f"bootstrap_seed must be {BOOTSTRAP_SEED}")
    if comparison.get("bootstrap_resamples") != BOOTSTRAP_RESAMPLES:
        raise ValueError(f"bootstrap_resamples must be {BOOTSTRAP_RESAMPLES}")
    if comparison.get("bootstrap_unit") != "protein":
        raise ValueError("bootstrap_unit must be 'protein'")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, count, size=(BOOTSTRAP_RESAMPLES, count))
    source_quantiles = np.quantile(values[CENTROID][indices].mean(axis=1), [0.025, 0.975])
    persistence_quantiles = np.quantile(
        values[PERSISTENCE][indices].mean(axis=1), [0.025, 0.975]
    )
    ci_checks = {
        SOURCE_CI: _ci_check(comparison.get(SOURCE_CI), source_quantiles),
        PERSISTENCE_CI: _ci_check(comparison.get(PERSISTENCE_CI), persistence_quantiles),
    }

    leave_one_out = []
    totals = {field: float(array.sum()) for field, array in values.items()}
    for row in rows:
        leave_one_out.append({
            "omitted_domain_id": row["domain_id"],
            "means": {
                field: (totals[field] - float(row[field])) / (count - 1)
                for field in metric_fields
            },
        })
    all_checks = [*scalar_checks.values(), *fraction_checks.values(), *ci_checks.values()]
    return {
        "scope": "published-summary arithmetic checks using retained per-protein receipts",
        "protein_count": count,
        "recomputed_protein_macro_means": means,
        "wins": wins,
        "scalar_checks": scalar_checks,
        "fraction_checks": fraction_checks,
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
            "unit": "protein",
            "algorithm": "numpy.default_rng integers; shared resample indices; numpy linear quantiles",
            "ci_checks": ci_checks,
            "algorithm_match_is_not_assumed_when_quantiles_differ": True,
        },
        "leave_one_protein_out": leave_one_out,
        "all_published_arithmetic_matched": all(check["matched"] for check in all_checks),
        "limitations": [
            "The receipt contains summary metrics; recomputing energy score requires raw coordinate arrays.",
            "Whether single_sample means an expected draw over K or a designated first sample is ambiguous and requires protocol verification.",
        ],
    }


def audit_release(release_dir: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(release_dir) / RECEIPT_PATH
    raw = path.read_bytes()
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid full-transition receipt JSON: {exc}") from exc
    report = audit_receipt(receipt)
    report["input_receipt"] = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=Path("artifacts/hf-release"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/receipt-audit.json"))
    args = parser.parse_args(argv)
    try:
        report = audit_release(args.release_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())
    return 0 if report["all_published_arithmetic_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
