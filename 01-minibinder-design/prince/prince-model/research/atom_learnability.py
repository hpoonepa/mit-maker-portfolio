#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Is the antibody-epitope label learnable from target geometry at all?

The univariate screen said no single feature of either block separates epitope
from non-epitope residues once the pool is restricted to solvent-exposed
residues (best within-context rank AUC ~0.60 out of 155 features). This asks the
next question: does *any* function of those features do better, and what is the
ceiling?

Four readings, in increasing order of how much they are allowed to know:

``cross_context``
    Fit on residues from one set of antigens, rank residues on antigens the
    model has never seen, grouped by sequence cluster so a near-duplicate
    antigen cannot sit on both sides of the split. This is the number that
    matters for a predictor.
``same_context_refit``
    Fit and evaluate on the *same* antigen's residues. Requested as a ceiling
    probe. It is not one -- a flexible model with 155 continuous features over a
    few hundred rows can memorise any label -- so it is reported and then
    discounted. It measures capacity, not explainability.
``within_context_random_cv``
    Fit on a random 2/3 of one antigen's exposed residues, rank the held-out
    1/3. Epitopes are spatially contiguous and neighbouring residues share
    almost identical neighbourhood features, so a random split leaks the answer
    across the fold boundary. An optimistic bound.
``within_context_spatial_cv``
    Same, but the held-out residues are a contiguous patch of surface (k-means
    on the residue coordinates, leave-one-block-out). The model must generalise
    to a region of the same protein it did not see. This is the honest ceiling
    on per-target learnability.

If ``within_context_spatial_cv`` sits at chance, the label is not a function of
target geometry at the resolution these features carry, and neither more data
nor more features will fix it.

Splits: fitting and reporting use TRAIN-split instances only, and any context
carrying a val or test instance is dropped outright so the locked evaluation
stays clean. Nothing here writes into the feature cache.
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold

HERE = Path(__file__).resolve().parent
CACHE_DIR = DATA / 'cache_full_antigen'
ATOM_DIR = DATA / 'atom_cache'
OUT_PATH = DATA / 'atom_learnability.json'

EXPOSED_RSA = 0.20
MIN_POSITIVE = 5
MIN_NEGATIVE = 5
SPATIAL_BLOCKS = 4
SEED = 0


def _read_cache(path: Path) -> dict:
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def _zscore(x: np.ndarray) -> np.ndarray:
    """Standardise within one context.

    A ranker compares residues on one target, so between-protein scale is not
    information it can use; pooling raw values would let the largest antigen set
    the scale for every feature.
    """
    sd = x.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (x - x.mean(axis=0)) / sd


def load_contexts(limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    skipped = {"no_train": 0, "has_eval_split": 0, "too_few": 0, "no_atom": 0}
    paths = sorted(CACHE_DIR.glob("*.json.gz"))
    if limit:
        paths = paths[:limit]
    for path in paths:
        cache = _read_cache(path)
        splits = {i.get("split") for i in cache["instances"]}
        if "train" not in splits:
            skipped["no_train"] += 1
            continue
        if splits & {"val", "test"}:
            # Keep the locked evaluation untouched: an antigen that appears in
            # val or test must not be fitted on here, even under its train label.
            skipped["has_eval_split"] += 1
            continue
        npz_path = ATOM_DIR / f"{cache['context_id']}.npz"
        if not npz_path.exists():
            skipped["no_atom"] += 1
            continue
        held = np.load(npz_path, allow_pickle=False)
        if list(held["keys"]) != cache["keys"]:
            raise ValueError(f"atom cache misaligned for {cache['context_id']}")
        epitope: set[str] = set()
        clusters: list[str] = []
        for inst in cache["instances"]:
            if inst.get("split") != "train":
                continue
            epitope.update(inst.get("epitope") or [])
            if inst.get("cluster"):
                clusters.append(str(inst["cluster"]))
        if not epitope:
            skipped["no_train"] += 1
            continue
        base = np.asarray(cache["features"], dtype=float)
        atom = held["feat"].astype(float)
        label = np.asarray([d in epitope for d in cache["display_keys"]])
        rsa = base[:, cache["feature_names"].index("relative_sasa")]
        keep = (rsa >= EXPOSED_RSA) | label
        base, atom, label = base[keep], atom[keep], label[keep]
        coords = np.asarray(cache["coordinates"], dtype=float)[keep]
        if label.sum() < MIN_POSITIVE or (~label).sum() < MIN_NEGATIVE:
            skipped["too_few"] += 1
            continue
        rows.append(
            {
                "context": cache["context_id"],
                "pdb": cache["pdb"],
                "cluster": clusters[0] if clusters else cache["context_id"],
                "base": _zscore(base),
                "atom": _zscore(atom),
                "raw_rsa": rsa[keep],
                "coords": coords,
                "label": label,
            }
        )
    return rows, skipped


def _model(kind: str):
    if kind == "linear":
        return LogisticRegression(max_iter=3000, C=1.0)
    return HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.08, max_leaf_nodes=31, random_state=SEED
    )


def _matrix(ctx: dict, block: str) -> np.ndarray:
    if block == "base":
        return ctx["base"]
    if block == "atom":
        return ctx["atom"]
    return np.hstack([ctx["base"], ctx["atom"]])


def _auc(label: np.ndarray, score: np.ndarray) -> float | None:
    if label.sum() == 0 or (~label).sum() == 0:
        return None
    return float(roc_auc_score(label, score))


def _spread(values: list[float]) -> dict:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    if arr.size == 0:
        return {"n": 0}
    return {
        "n": int(arr.size),
        "mean": round(float(arr.mean()), 4),
        "std": round(float(arr.std()), 4),
        "median": round(float(np.median(arr)), 4),
        "q25": round(float(np.percentile(arr, 25)), 4),
        "q75": round(float(np.percentile(arr, 75)), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
        "frac_above_0.5": round(float((arr > 0.5).mean()), 4),
    }


def cross_context(contexts: list[dict], block: str, kind: str, folds: int) -> dict:
    """Fit on some antigens, rank residues on antigens never seen, by cluster."""
    groups = np.asarray([c["cluster"] for c in contexts])
    index = np.arange(len(contexts))
    n_groups = len(set(groups.tolist()))
    splitter = GroupKFold(n_splits=min(folds, n_groups))
    per_context: list[float] = []
    for fit_idx, eval_idx in splitter.split(index, groups=groups):
        x_fit = np.vstack([_matrix(contexts[i], block) for i in fit_idx])
        y_fit = np.concatenate([contexts[i]["label"] for i in fit_idx])
        model = _model(kind)
        model.fit(x_fit, y_fit)
        for i in eval_idx:
            ctx = contexts[i]
            score = model.predict_proba(_matrix(ctx, block))[:, 1]
            per_context.append(_auc(ctx["label"], score))
    return _spread(per_context)


def same_context_refit(contexts: list[dict], block: str, kind: str) -> dict:
    """Capacity check: fit and score the same rows. Not a generalisation number."""
    out: list[float] = []
    for ctx in contexts:
        x, y = _matrix(ctx, block), ctx["label"]
        model = _model(kind)
        model.fit(x, y)
        out.append(_auc(y, model.predict_proba(x)[:, 1]))
    return _spread(out)


def within_context_cv(
    contexts: list[dict], block: str, kind: str, spatial: bool
) -> dict:
    """Per-target cross-validation, split either at random or by surface region."""
    out: list[float] = []
    for ctx in contexts:
        x, y = _matrix(ctx, block), ctx["label"]
        scores = np.full(len(y), np.nan)
        if spatial:
            k = min(SPATIAL_BLOCKS, len(y) // 8) or 1
            if k < 2:
                continue
            blocks = KMeans(n_clusters=k, n_init=5, random_state=SEED).fit_predict(
                ctx["coords"]
            )
            folds = [(np.flatnonzero(blocks != b), np.flatnonzero(blocks == b)) for b in range(k)]
        else:
            if y.sum() < 3 or (~y).sum() < 3:
                continue
            splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
            folds = list(splitter.split(x, y))
        for fit_idx, eval_idx in folds:
            if fit_idx.size == 0 or eval_idx.size == 0:
                continue
            if y[fit_idx].sum() < 2 or (~y[fit_idx]).sum() < 2:
                continue
            model = _model(kind)
            model.fit(x[fit_idx], y[fit_idx])
            scores[eval_idx] = model.predict_proba(x[eval_idx])[:, 1]
        done = ~np.isnan(scores)
        if done.sum() < 10:
            continue
        out.append(_auc(y[done], scores[done]))
    return _spread(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--kinds", nargs="*", default=["gbm", "linear"])
    args = ap.parse_args()

    contexts, skipped = load_contexts(args.limit)
    if not contexts:
        raise SystemExit(f"no usable train contexts (skipped: {skipped})")
    n_pos = sum(int(c["label"].sum()) for c in contexts)
    n_neg = sum(int((~c["label"]).sum()) for c in contexts)
    clusters = len({c["cluster"] for c in contexts})
    print(
        f"contexts={len(contexts)} clusters={clusters} "
        f"epitope={n_pos} exposed_other={n_neg} base_rate={n_pos/(n_pos+n_neg):.3f}",
        flush=True,
    )
    print(f"skipped: {skipped}", flush=True)

    # Reference points that involve no fitting at all.
    rsa_auc = [_auc(c["label"], -c["raw_rsa"]) for c in contexts]
    report: dict = {
        "setup": {
            "pool": f"relative_sasa >= {EXPOSED_RSA} or epitope",
            "contexts": len(contexts),
            "clusters": clusters,
            "epitope_residues": n_pos,
            "exposed_non_epitope_residues": n_neg,
            "base_rate": round(n_pos / (n_pos + n_neg), 4),
            "splits_used": "train-split instances only; val/test contexts excluded",
            "skipped": skipped,
            "within_context_zscored": True,
        },
        "baselines": {
            "rank_by_negative_relative_sasa": _spread(rsa_auc),
        },
        "results": {},
    }

    for kind in args.kinds:
        for block, n_feat in (("base", 51), ("atom", 104), ("both", 155)):
            key = f"{kind}/{block}({n_feat})"
            report["results"][key] = {
                "cross_context_groupkfold": cross_context(
                    contexts, block, kind, args.folds
                )
            }
            print(f"{key} cross_context: {report['results'][key]['cross_context_groupkfold']}", flush=True)

    # Ceiling ladder, on the strongest feature set and the flexible model only.
    ceiling = {}
    ceiling["same_context_refit_CAPACITY_ONLY"] = same_context_refit(
        contexts, "both", "gbm"
    )
    print(f"ceiling same_context_refit: {ceiling['same_context_refit_CAPACITY_ONLY']}", flush=True)
    ceiling["within_context_random_cv_OPTIMISTIC"] = within_context_cv(
        contexts, "both", "gbm", spatial=False
    )
    print(f"ceiling within_random: {ceiling['within_context_random_cv_OPTIMISTIC']}", flush=True)
    ceiling["within_context_spatial_cv_HONEST"] = within_context_cv(
        contexts, "both", "gbm", spatial=True
    )
    print(f"ceiling within_spatial: {ceiling['within_context_spatial_cv_HONEST']}", flush=True)
    report["ceiling_probe"] = ceiling

    Path(args.out).write_text(json.dumps(report, indent=1))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
