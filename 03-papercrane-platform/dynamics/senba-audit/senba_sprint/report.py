"""Write a bounded, descriptive report for frozen paired-evaluator records."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .metrics import analyze_records


_PRIMARY = ("centroid_rmsd", "mean_sample_rmsd", "energy_score")
_SPREAD = ("ensemble_variance", "pairwise_rmsd")
_IDS = ("protein_id", "replica_id", "start_id", "training_seed", "inference_seed")


def _read_records(paths: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        try:
            with path.open() as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
                    if not isinstance(record, dict):
                        raise ValueError(f"{path}:{line_number}: record must be an object")
                    records.append(record)
        except OSError as exc:
            raise ValueError(f"cannot read {path}: {exc}") from exc
    if not records:
        raise ValueError("at least one JSONL record is required")
    return records


def _rmsd(start: Any, target: Any) -> float:
    start = np.asarray(start, dtype=float)
    target = np.asarray(target, dtype=float)
    return float(np.sqrt(np.mean(np.sum((start - target) ** 2, axis=-1))))


def _raw_coordinate_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    required = {"target", "source", "candidate"}
    present = sum(isinstance(row.get("raw_coordinates"), dict) and required <= set(row["raw_coordinates"])
                  for row in records)
    return {
        "records_with_raw_ca_coordinates": present,
        "n_records": len(records),
        "status": "RAW_CA_COORDINATES_PRESENT" if present == len(records)
        else "RAW_CA_COORDINATES_MISSING_OR_INCOMPLETE_GENERIC_RECORDS_ALLOWED",
    }


def _add_persistence(analysis: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {tuple(row[field] for field in _IDS): row for row in records}
    units: dict[tuple[str, str, str, str], list[dict[str, float]]] = defaultdict(list)
    for transition in analysis["per_transition"]:
        ids = transition["ids"]
        row = by_id[tuple(ids[field] for field in _IDS)]
        baseline = _rmsd(row["start"], row["target"])
        values = {
            "persistence_ca_rmsd": baseline,
            "source_centroid_rmsd_gain": baseline - transition["source"]["centroid_rmsd"],
            "candidate_centroid_rmsd_gain": baseline - transition["candidate"]["centroid_rmsd"],
        }
        transition["persistence"] = values
        units[(ids["training_seed"], ids["protein_id"], ids["replica_id"], ids["start_id"])].append(values)
    # Repeated inference IDs for a physical transition are averaged before the
    # protein macro summary; never concatenate different ensemble sizes.
    per_protein: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for (seed, protein, _, _), values in units.items():
        per_protein[(seed, protein)].append({key: float(np.mean([item[key] for item in values])) for key in values[0]})
    return [
        {"training_seed": seed, "protein_id": protein, "n_transition_units": len(values),
         **{key: float(np.mean([item[key] for item in values])) for key in values[0]}}
        for (seed, protein), values in sorted(per_protein.items())
    ]


def build_report(records: list[dict[str, Any]], n_bootstrap: int = 2000) -> dict[str, Any]:
    """Return descriptive results; this function makes no scientific inference."""
    ensemble_sizes = {len(row.get("source", [])) for row in records if isinstance(row.get("source"), list)}
    if len(ensemble_sizes) > 1:
        raise ValueError("mixed ensemble sizes are not combinable; report each K separately")
    analysis = analyze_records(records, n_bootstrap=n_bootstrap)
    persistence = _add_persistence(analysis, records)
    raw_status = _raw_coordinate_status(records)
    max_identity = max(
        abs(transition[side]["mse_identity_residual"])
        for transition in analysis["per_transition"] for side in ("source", "candidate")
    )
    per_seed = []
    cis = {row["training_seed"]: row["ci_percentile"] for row in analysis["bootstrap"]}
    persistence_by_seed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in persistence:
        persistence_by_seed[row["training_seed"]].append(row)
    for seed in analysis["per_seed"]:
        protein_rows = persistence_by_seed[seed["training_seed"]]
        per_seed.append({
            "training_seed": seed["training_seed"], "n_proteins": len(protein_rows),
            "candidate_minus_source": seed["protein_macro_delta"],
            "ci_percentile": {metric: cis[seed["training_seed"]][metric] for metric in _PRIMARY},
            "spread_changes_no_desired_sign": {metric: seed["protein_macro_delta"][metric] for metric in _SPREAD},
            "persistence": {key: float(np.mean([row[key] for row in protein_rows])) for key in (
                "persistence_ca_rmsd", "source_centroid_rmsd_gain", "candidate_centroid_rmsd_gain")},
        })
    n_proteins = analysis["run"]["n_proteins"]
    warnings = [
        "Validation-panel results use a new evaluator and are not an exact reproduction of earlier results.",
        "All candidate-minus-source deltas are descriptive; no independent test-set claim is made.",
        "Spread changes have no desired sign and different K values are reported separately, never concatenated.",
    ]
    if n_proteins == 1:
        warnings.append("TECHNICAL_PILOT_ONLY: one protein gives a degenerate protein bootstrap; no scientific significance or inference is reported.")
    if n_proteins == 8:
        warnings.append("The prespecified eight-protein validation panel is reused; it is not an independent test set and cannot support selection claims.")
    return {
        "analysis": analysis,
        "report": {
            "counts": {**analysis["run"], "ensemble_sizes": sorted(ensemble_sizes)},
            "raw_coordinate_provenance": raw_status,
            "per_protein_persistence": persistence,
            "per_seed_summary": per_seed,
            "max_absolute_mse_decomposition_identity_residual": max_identity,
            "warnings": warnings,
        },
    }


def _markdown(result: dict[str, Any]) -> str:
    report = result["report"]
    counts = report["counts"]
    lines = [
        "# SENBA frozen paired-evaluator report", "",
        "Validation-panel descriptive results from a new evaluator; not an independent test result.", "",
        "## Counts", "",
        f"- Records: {counts['n_records']}; transition units: {counts['n_transition_units']}; proteins: {counts['n_proteins']}; training seeds: {counts['n_training_seeds']}; K: {counts['ensemble_sizes']}",
        f"- Raw C-alpha coordinates: {report['raw_coordinate_provenance']['status']} ({report['raw_coordinate_provenance']['records_with_raw_ca_coordinates']}/{counts['n_records']})",
        f"- Maximum absolute MSE decomposition identity residual: {report['max_absolute_mse_decomposition_identity_residual']:.3g}", "",
        "## Equal-protein summaries", "",
    ]
    for row in report["per_seed_summary"]:
        delta = row["candidate_minus_source"]
        ci = row["ci_percentile"]
        persistence = row["persistence"]
        lines.extend([
            f"### Training seed {row['training_seed']} ({row['n_proteins']} proteins)", "",
            "| Quantity | Candidate − source | Protein-bootstrap 95% interval |",
            "| --- | ---: | ---: |",
            *[f"| {metric} | {delta[metric]:.4g} | [{ci[metric]['low']:.4g}, {ci[metric]['high']:.4g}] |" for metric in _PRIMARY],
            *[f"| {metric} (spread; no desired sign) | {delta[metric]:.4g} | — |" for metric in _SPREAD],
            "",
            f"Persistence C-alpha RMSD: {persistence['persistence_ca_rmsd']:.4g}; candidate centroid-RMSD gain versus persistence: {persistence['candidate_centroid_rmsd_gain']:.4g}; source gain: {persistence['source_centroid_rmsd_gain']:.4g}.",
            "",
        ])
    lines.extend(["## Boundaries", "", *[f"- {warning}" for warning in report["warnings"]], ""])
    return "\n".join(lines)


def _plot(result: dict[str, Any], output: Path) -> None:
    import matplotlib.pyplot as plt

    rows = result["analysis"]["per_protein"]
    labels = [f"{row['training_seed']}:{row['protein_id']}" for row in rows]
    centroid = [row["delta"]["centroid_rmsd"] for row in rows]
    energy = [row["delta"]["energy_score"] for row in rows]
    figure, axes = plt.subplots(1, 2, figsize=(10, max(3, len(rows) * .45)))
    for axis, values, title in zip(axes, (centroid, energy), ("Centroid RMSD delta", "Energy-score delta")):
        axis.barh(labels, values)
        axis.axvline(0, color="black", linewidth=.8)
        axis.set_title(title + " (negative better)")
        axis.set_xlabel("candidate − source")
    figure.suptitle("Validation panel: new evaluator; no independent test")
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, action="append", required=True, help="records.jsonl; repeat for separate proteins")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError(f"output directory already exists: {args.output_dir}")
        records = _read_records(args.records)
        result = build_report(records)
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "analysis.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        (args.output_dir / "results.md").write_text(_markdown(result))
        if args.plot:
            _plot(result, args.output_dir / "forest.png")
        return 0
    except (OSError, TypeError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
