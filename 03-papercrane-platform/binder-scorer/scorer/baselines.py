"""baselines.py — The baseline ladder (Tasks A4 + A5).

Every baseline has the SAME signature::

    fn(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]

and returns the *test* designs ranked best-first (rank 1 == most likely binder).
``train_labels`` is a list[bool] parallel to ``train_designs`` (True == confirmed
binder). Baselines that need no training ignore the first two args.

Ladder:
  B0  within-fold min_ipSAE   — the bar to beat (no training).
  B1  within-fold ipTM        — established confidence-score baseline.
  B3  Overath logistic        — LR on [best_ipsae, shape_complementarity,
                                 rmsd_binder]; per-fold mean imputation +
                                 standardisation (LR needs no-NaN).
  B4  null random             — deterministic pseudo-random floor.
  B5  target-feature-conditioned LGBM — B6's matrix AUGMENTED with per-target
                                 sequence-based features (SS/charge/disorder) +
                                 one-hot interface_class. Falls back to B6 only
                                 if data/processed/target_features.csv is missing.
  B6  global LGBM             — LightGBM over the full numeric feature matrix,
                                 raw NaN passed through (LightGBM-native).

B2 is intentionally omitted.
"""

from __future__ import annotations

import csv
import logging
import math
import os
from typing import Sequence

import numpy as np

from scorer.data_loader import LGBM_FEATURE_KEYS, OVERATH_FEATURE_KEYS
from scorer.eval_types import ScoredDesignDict, make_scored_design
from scorer.llm_prior import load_priors

_logger = logging.getLogger(__name__)

_NEG_INF = float("-inf")

# ---------------------------------------------------------------------------
# Target-side features (B5). Loaded once and cached, keyed by NORMALIZED
# (upper-cased) target name. NaN-filled for any missing numeric cell so
# LightGBM consumes it natively.
# ---------------------------------------------------------------------------
TARGET_FEATURES_CSV = os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "target_features.csv"
)

# Numeric target-feature columns added to the LGBM matrix (in this order).
_TARGET_NUMERIC_KEYS: tuple[str, ...] = (
    "log_length",
    "disorder_fraction",
    "frac_helix",
    "frac_strand",
    "frac_loop",
    "pocket_volume",
    "druggability",
    "epitope_hydrophobicity",
    "epitope_net_charge",
    "frac_polar",
)
# One-hot categories for interface_class (kept stable incl. ligand_present,
# which the sequence proxy never emits but the schema reserves).
_INTERFACE_CLASSES: tuple[str, ...] = (
    "helical",
    "sheet_flat",
    "mixed",
    "ligand_present",
)

_TARGET_FEATURES_CACHE: dict | None = None


def _load_target_features(path: str = TARGET_FEATURES_CSV) -> dict | None:
    """Load target_features.csv -> {NORMALIZED_TARGET: row dict}.

    Returns ``None`` if the CSV is entirely missing (B5 then falls back to B6).
    Cached at module level. Empty/'nan' numeric cells become float NaN.
    """
    global _TARGET_FEATURES_CACHE
    if _TARGET_FEATURES_CACHE is not None:
        return _TARGET_FEATURES_CACHE
    if not os.path.exists(path):
        return None
    table: dict[str, dict] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("target") or "").strip().upper()
            if name:
                table[name] = row
    _TARGET_FEATURES_CACHE = table
    return table


def _to_float(value) -> float:
    if value is None:
        return float("nan")
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "na", "none", "null"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _target_feature_vector(target: str, table: dict) -> list[float]:
    """Numeric + one-hot interface_class vector for a target.

    Missing target -> all NaN numerics and an all-zero one-hot (no class info).
    """
    row = table.get((target or "").strip().upper())
    if row is None:
        return [float("nan")] * len(_TARGET_NUMERIC_KEYS) + [0.0] * len(
            _INTERFACE_CLASSES
        )
    nums = [_to_float(row.get(k)) for k in _TARGET_NUMERIC_KEYS]
    iface = (row.get("interface_class") or "").strip().lower()
    onehot = [1.0 if iface == c else 0.0 for c in _INTERFACE_CLASSES]
    return nums + onehot


_TARGET_FEATURE_NAMES: tuple[str, ...] = _TARGET_NUMERIC_KEYS + tuple(
    f"interface_class__{c}" for c in _INTERFACE_CLASSES
)


def _rank(pairs: list[tuple[str, float]]) -> list[ScoredDesignDict]:
    """Given (design_id, score) pairs, return best-first ScoredDesignDicts.

    Higher score = better. NaN scores sort last. Ties broken by design_id for
    determinism.
    """
    def key(p):
        did, sc = p
        s = _NEG_INF if (sc is None or (isinstance(sc, float) and math.isnan(sc))) else sc
        return (-s, did)

    ordered = sorted(pairs, key=key)
    return [make_scored_design(did, sc, i + 1) for i, (did, sc) in enumerate(ordered)]


# ---------------------------------------------------------------------------
# B0 — within-fold min_ipSAE (no training)
# ---------------------------------------------------------------------------
def b0_within_fold_min_ipsae(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    pairs = [(d["design_id"], d.get("best_ipsae", _NEG_INF)) for d in test_designs]
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B1 — within-fold Boltz-2 ipTM (no training)
# ---------------------------------------------------------------------------
def b1_within_fold_iptm(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    pairs = [
        (
            d["design_id"],
            d.get("features", {}).get(
                "computational__boltz2_iptm",
                d.get("iptm", _NEG_INF),
            ),
        )
        for d in test_designs
    ]
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B4 — deterministic pseudo-random floor
# ---------------------------------------------------------------------------
def b4_null_random(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    import hashlib

    pairs = []
    for d in test_designs:
        h = hashlib.sha1(d["design_id"].encode()).hexdigest()
        pairs.append((d["design_id"], int(h, 16) % (10**8) / 1e8))
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B3 — Overath validated 3-feature logistic regression
# ---------------------------------------------------------------------------
def b3_overath_logistic(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    from sklearn.linear_model import LogisticRegression

    keys = OVERATH_FEATURE_KEYS
    X_train = np.array(
        [[d["features"][k] for k in keys] for d in train_designs], dtype=float
    )
    y_train = np.array([1 if b else 0 for b in train_labels], dtype=int)
    X_test = np.array(
        [[d["features"][k] for k in keys] for d in test_designs], dtype=float
    )

    # per-fold train-column means for imputation (LR cannot take NaN)
    col_means = np.nanmean(X_train, axis=0)
    col_means = np.where(np.isnan(col_means), 0.0, col_means)
    X_train = np.where(np.isnan(X_train), col_means, X_train)
    X_test = np.where(np.isnan(X_test), col_means, X_test)

    # standardise on train stats
    mu = X_train.mean(axis=0)
    sd = X_train.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    X_train = (X_train - mu) / sd
    X_test = (X_test - mu) / sd

    # degenerate single-class train -> fall back to B0 ranking
    if len(np.unique(y_train)) < 2:
        return b0_within_fold_min_ipsae(train_labels, train_designs, test_designs)

    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(X_train, y_train)
    proba = clf.predict_proba(X_test)[:, 1]
    pairs = [(d["design_id"], float(p)) for d, p in zip(test_designs, proba)]
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B6 — global LightGBM over the full numeric feature set (NaN-native)
# ---------------------------------------------------------------------------
def b6_global_lgbm(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    import lightgbm as lgb

    keys = LGBM_FEATURE_KEYS
    X_train = np.array(
        [[d["features"][k] for k in keys] for d in train_designs], dtype=float
    )
    y_train = np.array([1 if b else 0 for b in train_labels], dtype=int)
    X_test = np.array(
        [[d["features"][k] for k in keys] for d in test_designs], dtype=float
    )

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    if n_pos == 0 or n_neg == 0:
        # degenerate single-class train -> fall back to B0
        return b0_within_fold_min_ipsae(train_labels, train_designs, test_designs)

    scale_pos_weight = n_neg / n_pos
    params = {
        "objective": "binary",
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 3,
        "learning_rate": 0.05,
        "scale_pos_weight": scale_pos_weight,
        "deterministic": True,
        "num_threads": 1,
        "seed": 0,
        "verbose": -1,
    }
    dtrain = lgb.Dataset(X_train, label=y_train, feature_name=list(keys))
    booster = lgb.train(params, dtrain, num_boost_round=200)
    proba = booster.predict(X_test)
    pairs = [(d["design_id"], float(p)) for d, p in zip(test_designs, proba)]
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B5 — target-feature-conditioned LGBM (falls back to B6 until built)
# ---------------------------------------------------------------------------
def b5_target_feature_conditioned_lgbm(train_labels, train_designs, test_designs) -> list[ScoredDesignDict]:
    """Global LightGBM AUGMENTED with target-side features (Task 3).

    Same LightGBM params as B6, but the feature matrix is extended with the
    per-target sequence-based features (log_length, disorder/SS fractions,
    pocket_volume/druggability [NaN], epitope hydrophobicity/charge, polar) plus
    a one-hot of interface_class. Designs whose target has no features row get
    NaN numerics + an all-zero one-hot (LightGBM handles NaN natively). Only if
    the CSV is ENTIRELY missing does B5 fall back to B6.

    NOTE: these target features are SEQUENCE-BASED proxies (Chou-Fasman SS, no
    real structure/pockets) — see scorer/target_features.py.
    """
    import lightgbm as lgb

    table = _load_target_features()
    if table is None:
        # CSV entirely missing -> documented fall back to B6.
        return b6_global_lgbm(train_labels, train_designs, test_designs)

    keys = LGBM_FEATURE_KEYS
    feat_names = list(keys) + list(_TARGET_FEATURE_NAMES)

    def _row(d):
        base = [d["features"][k] for k in keys]
        return base + _target_feature_vector(d.get("target", ""), table)

    X_train = np.array([_row(d) for d in train_designs], dtype=float)
    y_train = np.array([1 if b else 0 for b in train_labels], dtype=int)
    X_test = np.array([_row(d) for d in test_designs], dtype=float)

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    if n_pos == 0 or n_neg == 0:
        # degenerate single-class train -> fall back to B0
        return b0_within_fold_min_ipsae(train_labels, train_designs, test_designs)

    scale_pos_weight = n_neg / n_pos
    params = {
        "objective": "binary",
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 3,
        "learning_rate": 0.05,
        "scale_pos_weight": scale_pos_weight,
        "deterministic": True,
        "num_threads": 1,
        "seed": 0,
        "verbose": -1,
    }
    dtrain = lgb.Dataset(X_train, label=y_train, feature_name=feat_names)
    booster = lgb.train(params, dtrain, num_boost_round=200)
    proba = booster.predict(X_test)
    pairs = [(d["design_id"], float(p)) for d, p in zip(test_designs, proba)]
    return _rank(pairs)


# ---------------------------------------------------------------------------
# B_LLM — LLM-per-target SIGNED prior scorer (the meta-scorer differentiator)
# ---------------------------------------------------------------------------
LLM_PRIORS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "llm_priors.json"
)
_DEFAULT_PRIORS: dict | None = None  # lazily loaded {target: Prior}, cached once


def _default_priors() -> dict:
    """Lazily load + cache the live priors file. Missing file -> {} (-> B0)."""
    global _DEFAULT_PRIORS
    if _DEFAULT_PRIORS is None:
        _DEFAULT_PRIORS = (
            load_priors(LLM_PRIORS_PATH) if os.path.exists(LLM_PRIORS_PATH) else {}
        )
    return _DEFAULT_PRIORS


def _llm_metric_value(design: dict, key: str):
    """Alias-aware metric lookup. Returns the raw value or None if absent.

    The data folds boltz2_min_ipsae into best_ipsae, so the single most
    important weight key must alias to best_ipsae or it would be silently
    skipped.
    """
    if key in ("computational__boltz2_min_ipsae", "best_ipsae"):
        return design.get("best_ipsae")
    feats = design.get("features", {})
    return feats[key] if key in feats else None


def b_llm_prior(train_labels, train_designs, test_designs, *, priors=None, target=None) -> list[ScoredDesignDict]:
    """Rank test designs by a per-target, SIGNED, literature-informed prior.

    Weighted z-score sum over present metrics (train-only normalization), minus
    failure penalties. Falls back to B0 when no prior exists for the target.
    """
    if priors is None:
        priors = _default_priors()
    if target is None:
        target = test_designs[0].get("target", "") if test_designs else ""

    prior = priors.get(target)
    if prior is None:
        _logger.info("b_llm_prior: no prior for target %r; falling back to B0", target)
        return b0_within_fold_min_ipsae(train_labels, train_designs, test_designs)

    weights = prior.weights
    # Leakage-safe: TRAIN-only mean/std per weighted metric (nan-aware). Skip a
    # metric absent in train or with no spread (std == 0 / NaN).
    stats: dict[str, tuple[float, float]] = {}
    for k in weights:
        vals = np.array(
            [_to_float(_llm_metric_value(d, k)) for d in train_designs], dtype=float
        )
        if vals.size == 0 or np.all(np.isnan(vals)):
            continue
        mu = float(np.nanmean(vals))
        sd = float(np.nanstd(vals))
        if not math.isfinite(sd) or sd == 0.0:
            continue
        stats[k] = (mu, sd)

    pairs: list[tuple[str, float]] = []
    for d in test_designs:
        score = 0.0
        for k, (mu, sd) in stats.items():
            v = _to_float(_llm_metric_value(d, k))
            if math.isnan(v):
                continue  # test design missing this metric -> contributes 0
            # Weights are ALREADY SIGNED (positive = higher better, negative =
            # higher worse). Do NOT apply ENSEMBLE_INVERT_SUBSTRINGS here — that
            # legacy flip is for UNSIGNED ensembles and would double-negate the
            # LLM-provided sign (e.g. rmsd_binder / aggregation come back negative).
            score += weights[k] * ((v - mu) / sd)
        # Failure penalties: subtract P when a threshold rule fires. Defensive:
        # the live file stores some penalties as bare floats (not {gt,penalty}).
        for feat, rule in (prior.failure_penalties or {}).items():
            if not isinstance(rule, dict):
                continue
            fv = _to_float(_llm_metric_value(d, feat))
            penalty = rule.get("penalty")
            if math.isnan(fv) or penalty is None:
                continue
            if "gt" in rule and fv > rule["gt"]:
                score -= penalty
            elif "lt" in rule and fv < rule["lt"]:
                score -= penalty
        pairs.append((d["design_id"], score))
    return _rank(pairs)


# B_STACK — nested-LOTO blend of B_LLM + B6. Imported at the BOTTOM so the
# names it depends on (_rank, b_llm_prior, b6_global_lgbm) are already defined
# when scorer.stack resolves them; stack.py itself imports them lazily.
from scorer.stack import b_stack  # noqa: E402

BASELINE_LADDER: list[tuple[str, object]] = [
    ("B0", b0_within_fold_min_ipsae),
    ("B_IPTM", b1_within_fold_iptm),
    ("B3", b3_overath_logistic),
    ("B4", b4_null_random),
    ("B5", b5_target_feature_conditioned_lgbm),
    ("B6", b6_global_lgbm),
    ("B_LLM", b_llm_prior),
    ("B_STACK", b_stack),
]

BASELINE_BY_NAME = {name: fn for name, fn in BASELINE_LADDER}
