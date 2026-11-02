"""Validate prepared patch features and apply the published model unchanged."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any


def feature_schema() -> dict[str, Any]:
    return json.loads(files("prince_ranker").joinpath("data/feature_schema.json").read_text())


def select_diverse(scores: list[float], patches: list[list[str]], top: int) -> list[int]:
    """Stable descending rank, suppressing residue Jaccard overlap >= 0.5."""
    sets = [set(patch) for patch in patches]
    selected: list[int] = []
    for index in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
        if any(len(sets[index] & sets[j]) / len(sets[index] | sets[j]) >= 0.5 for j in selected):
            continue
        selected.append(index)
        if len(selected) == top:
            break
    return selected


def rank_patches(payload: dict[str, Any], top: int = 3) -> dict[str, Any]:
    """Score a prepared feature matrix; this function does not featurize coordinates.

    Each row must follow the bundled schema and use the frozen ESM projection.
    Outputs are model ranking scores, not calibrated binding probabilities.
    """
    if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= 10:
        raise ValueError("top must be an integer from 1 to 10")
    schema = feature_schema()
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("Expected an object with schema_version=1")
    if payload.get("feature_names") != schema["feature_names"]:
        raise ValueError("feature_names must match the bundled 660-column schema in order")
    if payload.get("pca_id") != schema["pca_id"]:
        raise ValueError("pca_id must match the frozen training projection")
    patches = payload.get("patches")
    if not isinstance(patches, list) or not 1 <= len(patches) <= 4096:
        raise ValueError("patches must contain between 1 and 4096 residue lists")
    for patch in patches:
        if (not isinstance(patch, list) or not patch
                or any(not isinstance(key, str) or not key.strip() for key in patch)
                or len(set(patch)) != len(patch)):
            raise ValueError("Each patch must contain unique, nonempty residue identifiers")
    rows = payload.get("features")
    if (not isinstance(rows, list) or len(rows) != len(patches)
            or any(not isinstance(row, list) or len(row) != 660 for row in rows)
            or any(type(value) not in (int, float) for row in rows for value in row)):
        raise ValueError("features must be a numeric matrix with one 660-column row per patch")
    try:
        import numpy as np
        import xgboost as xgb
    except ImportError as exc:
        raise RuntimeError("Install the ranker extra: python -m pip install '.[ranker]'") from exc
    matrix = np.asarray(rows, dtype=np.float32)
    if not np.isfinite(matrix).all():
        raise ValueError("features must contain finite numbers representable as float32")
    artifact = files("prince_ranker").joinpath("data/site_ranker.json").read_bytes()
    model = xgb.Booster(params={"nthread": 1})
    model.load_model(bytearray(artifact))
    if model.num_features() != matrix.shape[1]:
        raise RuntimeError("Installed model and feature schema disagree")
    scores = model.predict(xgb.DMatrix(matrix)).tolist()
    selected = select_diverse(scores, patches, top)
    return {
        "schema_version": 1,
        "model": "prince-site-ranker",
        "model_sha256": hashlib.sha256(artifact).hexdigest(),
        "pca_id": schema["pca_id"],
        "score_semantics": "uncalibrated patch classification score; not binding probability",
        "patches_scored": len(patches),
        "nms_jaccard_threshold": 0.5,
        "ranked": [{"rank": rank, "patch_index": index, "score": scores[index],
                    "residues": patches[index]} for rank, index in enumerate(selected, 1)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank prepared surface patches with the frozen PRINCE model.")
    parser.add_argument("input", nargs="?", type=Path, help="Prepared patch features in JSON")
    parser.add_argument("--top", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--output", type=Path, help="Write JSON to a file instead of stdout")
    parser.add_argument("--describe", action="store_true", help="Print the ordered feature schema")
    args = parser.parse_args()
    try:
        if args.describe:
            result = feature_schema()
        elif args.input:
            result = rank_patches(json.loads(args.input.read_text()), args.top)
        else:
            parser.error("provide an input file or --describe")
        encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(encoded)
        else:
            sys.stdout.write(encoded)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
