# SPDX-License-Identifier: MIT
"""Site proposal: rank surface patches as candidate binder sites.

**This is not a novel predictor and must not be described as one.** Ranking
sites is published prior art — Site4Drug (arXiv:2606.01816), SurfDiff,
DiscoTope-3.0, SEMA, ScanNet, PeSTo, MaSIF-site — and most of that work uses
trained models with real validation behind them. This package contains no
trained model, no learned embedding and no neural network; weights are
configuration.

What this stage is:

* :mod:`.geometric` — an honest interpretable baseline, four named features and
  untuned hand-set weights, so the tool works with nothing else installed.
* :mod:`.external` — an adapter that reads per-residue scores **you** generated
  with one of those published predictors, so it can be the backend instead.
  Nothing is downloaded, vendored or redistributed: DiscoTope-3.0's code is
  CC BY-NC-4.0 with no data grant and SEMA's licence file is boilerplate from an
  unrelated project, and this repository is MIT.
* :mod:`.registry` — name lookup and entry-point discovery, so a third-party
  backend can live in its own package under its own licence.

The project's contribution is the downstream assembly-aware filter, and the
claim that can actually be supported is **how much that filter improves
whichever predictor is plugged in here**. Swappability is what makes that
measurable.
"""

from __future__ import annotations

from .base import (
    AGGREGATES,
    EXTERNAL_PRIOR_DEFAULT_WEIGHT,
    LINEAR_AGGREGATES,
    N_OUTCOMES_FITTED,
    NMS_JACCARD_THRESHOLD,
    ScoredPatch,
    SitePredictor,
    jaccard,
    provenance,
    rank_patches,
    suppress_overlapping,
)
from .external import (
    MIN_MATCH_FRACTION,
    UNSCORED,
    ExternalPredictor,
    ExternalScoreError,
    ExternalScoreFile,
    LowResidueMatchWarning,
    load_external_score_file,
    load_external_scores,
    midrank_percentiles,
)
from .geometric import (
    DEFAULT_WEIGHTS,
    FEATURE_NAMES,
    GeometricPredictor,
    anchor_residues,
)
from .registry import (
    ENTRY_POINT_GROUP,
    PredictorPluginWarning,
    UnknownPredictorError,
    available,
    get,
    refresh,
    register,
)

__all__ = [
    "AGGREGATES",
    "LINEAR_AGGREGATES",
    "NMS_JACCARD_THRESHOLD",
    "EXTERNAL_PRIOR_DEFAULT_WEIGHT",
    "N_OUTCOMES_FITTED",
    "ScoredPatch",
    "SitePredictor",
    "jaccard",
    "provenance",
    "rank_patches",
    "suppress_overlapping",
    "DEFAULT_WEIGHTS",
    "FEATURE_NAMES",
    "GeometricPredictor",
    "anchor_residues",
    "ExternalPredictor",
    "ExternalScoreError",
    "ExternalScoreFile",
    "LowResidueMatchWarning",
    "MIN_MATCH_FRACTION",
    "UNSCORED",
    "load_external_score_file",
    "load_external_scores",
    "midrank_percentiles",
    "ENTRY_POINT_GROUP",
    "PredictorPluginWarning",
    "UnknownPredictorError",
    "available",
    "get",
    "refresh",
    "register",
]
