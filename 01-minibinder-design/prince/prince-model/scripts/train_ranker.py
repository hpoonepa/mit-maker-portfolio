#!/usr/bin/env python3
"""CPU-only, connected-component reanalysis of cached real structural features.

This is retrospective reanalysis, not a previously untouched external test set.
No features are regenerated, no network is used, and no LLM is trained.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from benchmark.evaluate import _antibody_chains, _split_field
from benchmark.metrics import per_residue_auroc, per_residue_auprc
from benchmark.cluster import _metas_from_cache, assign_clusters, assign_splits, cap_clusters

FEATURES = ("exposure", "concavity", "hydrophobicity", "connectivity")


def load_features(paths: list[Path]) -> dict:
    records = {}
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                if "res" not in row:
                    continue
                if row.get("residue_encoding") != "chain:seq[:icode]":
                    raise ValueError("Ambiguous legacy feature IDs; run scripts/repair_feature_records.py first")
                if row["id"] in records:
                    raise ValueError(f"duplicate feature instance: {row['id']}")
                matrix = np.asarray([r[1:] for r in row["res"]], dtype=float)
                if matrix.ndim != 2 or matrix.shape[1] != 5 or not np.isfinite(matrix).all():
                    raise ValueError(f"invalid feature matrix: {row['id']}")
                if not np.isin(matrix[:, 4], [0, 1]).all():
                    raise ValueError("labels must be binary")
                records[row["id"]] = matrix
    return records


def fit(features: np.ndarray, labels: np.ndarray) -> np.ndarray:
    design = np.column_stack((features, np.ones(len(features))))
    if len(np.unique(labels)) != 2:
        raise ValueError("training requires both classes")
    def objective(weights):
        z = design @ weights
        penalty = np.dot(weights[:-1], weights[:-1])
        value = (np.sum(np.logaddexp(0, z) - labels * z) + penalty) / len(labels)
        probability = np.exp(-np.logaddexp(0, -z))
        gradient = design.T @ (probability - labels)
        gradient[:-1] += 2 * weights[:-1]
        return value, gradient / len(labels)
    fitted = minimize(objective, np.zeros(5), jac=True, method="L-BFGS-B")
    if not fitted.success:
        raise RuntimeError(f"fit failed: {fitted.message}")
    return fitted.x


def evaluate(records: dict, ids: list[str], clusters: dict, weights: np.ndarray) -> dict:
    by_cluster = defaultdict(list)
    for instance in ids:
        matrix = records[instance]
        labels = matrix[:, 4].astype(bool)
        if len(np.unique(labels)) < 2:
            continue
        scores = matrix[:, :4] @ weights[:4] + weights[4]
        by_cluster[clusters[instance]].append([
            per_residue_auroc(scores, labels), per_residue_auprc(scores, labels)
        ])
    if not by_cluster:
        raise ValueError("no evaluable held-out clusters")
    values = np.array([np.mean(v, axis=0) for v in by_cluster.values()])
    rng = np.random.default_rng(0)
    boot = np.array([values[rng.integers(len(values), size=len(values))].mean(axis=0)
                     for _ in range(2000)])
    return {
        "macro_auroc": float(values[:, 0].mean()),
        "macro_auprc": float(values[:, 1].mean()),
        "auroc_ci95": np.quantile(boot[:, 0], [.025, .975]).tolist(),
        "auprc_ci95": np.quantile(boot[:, 1], [.025, .975]).tolist(),
        "n_instances": len(ids), "n_clusters": len(by_cluster),
        "aggregation": "within-instance metric, mean within cluster, mean across clusters",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/benchmark/manifest.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / ".cache/benchmark/rcsb")
    parser.add_argument("--features", type=Path, nargs="+",
                        default=[ROOT / "data/eval/features_corrected.jsonl.gz"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.open() as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    metadata = {}
    metadata_digest = hashlib.sha256()
    for pdb_id in sorted({r["pdb_id"].lower() for r in rows}):
        path = args.metadata / f"{pdb_id}.json"
        if not path.is_file():
            raise ValueError(f"missing local metadata {pdb_id}; refusing network or silent fallback")
        metadata_digest.update(pdb_id.encode() + b"\0" + path.read_bytes())
        metadata.update(_metas_from_cache(pdb_id, json.loads(path.read_text())))
    triples = [(r["instance_id"], r["pdb_id"], _split_field(r["antigen_chains"])) for r in rows]
    clusters = assign_clusters(triples, metadata)
    for _, pdb, chains in triples:
        if not all((pdb.lower(), c) in metadata for c in chains):
            raise ValueError(f"unresolved antigen metadata: {pdb} {chains}")
    resolution = {r["instance_id"]: float(r["resolution"] or "inf") for r in rows}
    kept, dropped = cap_clusters(clusters, rank=lambda i: (resolution[i],))
    splits = assign_splits(kept.values(), seed="prince-connected-v1")
    repaired = [{**r, "cluster_id": kept[r["instance_id"]],
                 "split": splits[kept[r["instance_id"]]]}
                for r in rows if r["instance_id"] in kept]
    identity_sets = {split: set() for split in ("train", "val", "test")}
    for row in repaired:
        for chain in _split_field(row["antigen_chains"]):
            meta = metadata[(row["pdb_id"].lower(), chain)]
            identity_sets[row["split"]].update(f"up:{a}" for a in meta.uniprot_accessions)
            if meta.sequence:
                identity_sets[row["split"]].add(f"seq:{meta.sequence_digest}")
    overlap = {f"{a}_{b}": len(identity_sets[a] & identity_sets[b])
               for a, b in (("train", "val"), ("train", "test"), ("val", "test"))}
    if any(overlap.values()):
        raise ValueError("Independent antigen identity audit found cross-split leakage")
    records = load_features(args.features)
    aliases = {
        f"{r['pdb_id']}:{'+'.join(_antibody_chains(r))}": r["instance_id"]
        for r in rows
    }
    if set(records) - set(aliases):
        raise ValueError("feature instance absent from source manifest")
    records = {aliases[key]: value for key, value in records.items()}
    split_ids = {s: [r["instance_id"] for r in repaired
                     if r["split"] == s and r["instance_id"] in records]
                 for s in ("train", "val", "test")}
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        if {kept[i] for i in split_ids[left]} & {kept[i] for i in split_ids[right]}:
            raise ValueError("connected component crosses split")
    train = np.concatenate([records[i] for i in split_ids["train"]])
    weights = fit(train[:, :4], train[:, 4])
    fitted = evaluate(records, split_ids["test"], kept, weights)
    exposure = evaluate(records, split_ids["test"], kept, np.array([1., 0, 0, 0, 0]))
    designability = evaluate(records, split_ids["test"], kept, np.array([.4, .3, .2, .1, 0]))
    repair_path = ROOT/"data/eval/feature_identity_repair.json"
    repair = json.loads(repair_path.read_text()) if repair_path.is_file() else {}
    if len(args.features) != 1 or repair.get("output_sha256") != hashlib.sha256(args.features[0].read_bytes()).hexdigest():
        repair = {}
    result = {
        "schema_version": 1, "model_type": "L2 logistic regression; not an LLM",
        "status": "retrospective_connected_component_reanalysis",
        "features": list(FEATURES), "weights": dict(zip(FEATURES, weights[:4].tolist())),
        "intercept": float(weights[4]), "l2": 1.0, "seed": "prince-connected-v1",
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [args.manifest, *args.features]},
        "metadata_sha256": metadata_digest.hexdigest(),
        "identity_overlap_audit": overlap,
        "protocol_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__).resolve(), ROOT/"scripts/featurise_benchmark.py",
                         ROOT/"scripts/repair_feature_records.py", ROOT/"benchmark/cluster.py")
        },
        "feature_identity_repair": {key: value for key, value in repair.items()
                                    if key != "instances_detail"},
        "manifest_instances": len(rows), "retained_instances": len(repaired),
        "excluded_by_component_cap": len(dropped),
        "excluded_instances": [{"id": identifier, "component": component,
                                "reason": "connected component cap 20"}
                               for identifier, component in dropped],
        "excluded_cached_feature_ids": sorted(set(records) - set(kept)),
        "retained_without_cached_features": len(repaired) - sum(map(len, split_ids.values())),
        "cached_feature_instances": len(records),
        "available_features_not_used": len(records) - sum(map(len, split_ids.values())),
        "split_instances": {s: len(ids) for s, ids in split_ids.items()},
        "split_clusters": {s: len({kept[i] for i in ids}) for s, ids in split_ids.items()},
        "split_ids": split_ids,
        "split_overlap_components": 0,
        "evaluation": {"fitted": fitted, "exposure_only": exposure, "designability": designability},
        "limitations": [
            "Cached features cover only a subset of the 8241-interface manifest.",
            "All cached features have appeared in earlier exploratory analyses; this is not an untouched external test.",
            "Connected accession/exact-sequence disjointness does not establish homology-disjointness.",
            "Antibody epitopes are not designed-minibinder outcome labels.",
            "No LLM training corpus/checkpoint exists; no trained-LLM or 83-percent recovery claim is supported.",
            "Residue AUROC and AUPRC are not patch recovery; see the separate connected-sites evaluation artifact.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    manifest_out = args.out.with_suffix(".manifest.csv")
    with manifest_out.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(repaired)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("split_ids", "sources", "excluded_instances", "excluded_cached_feature_ids")}, indent=2))


if __name__ == "__main__":
    main()
