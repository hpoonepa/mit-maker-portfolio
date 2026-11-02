"""Aggregate per-target result JSONs into the per_target dicts that
benchmark.compare_recovery expects, both for the ensemble pipeline and
the static baseline (apo-only fpocket)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from legacy_poc.benchmark import compare_recovery
from legacy_poc.datasets import (
    BenchmarkTarget,
    fetch_pdb,
    holo_ligand_centroid,
    load_pocketminer_benchmark,
)


def aggregate_results(
    per_target_jsons: list[Path],
    holo_centroids: dict[str, tuple[float, float, float]],
) -> tuple[list[dict], list[dict]]:
    ensemble: list[dict] = []
    static: list[dict] = []
    for jp in per_target_jsons:
        data = json.loads(Path(jp).read_text())
        target_id = data["apo_pdb_id"].lower()
        gt = holo_centroids.get(target_id)
        if gt is None:
            continue
        ensemble.append({
            "target": target_id,
            "ground_truth": gt,
            "predictions": [tuple(c["centroid"]) for c in data.get("cryptic_calls", [])],
        })
        static.append({
            "target": target_id,
            "ground_truth": gt,
            "predictions": [
                tuple(p["center"]) for p in data.get("apo_baseline_pockets", [])
            ],
        })
    return ensemble, static


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True, type=Path,
                    help="Dir of per-target *.json result files")
    ap.add_argument("--benchmark-csv", required=True, type=Path)
    ap.add_argument("--holo-dir", required=True, type=Path,
                    help="Dir to cache holo PDBs for centroid extraction")
    ap.add_argument("--distance-threshold", type=float, default=5.0)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    targets: list[BenchmarkTarget] = load_pocketminer_benchmark(args.benchmark_csv)
    holo_centroids: dict[str, tuple[float, float, float]] = {}
    for t in targets:
        try:
            holo_path = fetch_pdb(t.holo_pdb_id, args.holo_dir)
            holo_centroids[t.apo_pdb_id] = holo_ligand_centroid(holo_path, t.ligand_resname)
        except Exception as e:
            print(f"[warn] skipping {t.apo_pdb_id} ({t.holo_pdb_id}): {e}")

    json_paths = sorted(args.results_dir.glob("*.json"))
    ensemble, static = aggregate_results(json_paths, holo_centroids)
    summary = compare_recovery(ensemble, static, args.distance_threshold)
    summary["per_target_ensemble"] = ensemble
    summary["per_target_static"] = static
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, default=list))
    print(json.dumps(
        {k: v for k, v in summary.items()
         if k not in {"per_target_ensemble", "per_target_static"}},
        indent=2,
    ))


if __name__ == "__main__":
    main()
