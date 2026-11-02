# SPDX-License-Identifier: MIT
"""Making scores from different predictors comparable at all.

Separated from :mod:`.scorefile` because this is a statistical decision, not a
file-format one, and it applies to any ingested prior however it arrived.

Raw outputs from these tools are **incommensurable by construction**:
DiscoTope-3.0's ``calibrated_score`` is z-like and unbounded, BepiPred's
meaningful threshold is 0.1512, ScanNet's is a smoothed sigmoid. Averaging an
unbounded z-score over a patch is not the same operation as averaging a
probability, so raw values cannot be blended, compared across backends, or
thresholded with any single constant. Converting to within-target midrank
percentiles first is what makes the downstream arithmetic mean anything.
"""

from __future__ import annotations

import math
from typing import Mapping

from ..residue import ResidueKey

__all__ = ["UNSCORED", "midrank_percentiles"]

UNSCORED = float("nan")
"""What a profiled residue the file says nothing about scores: NaN, not 0.0.

This was 0.0 and that was wrong. Under the percentile normalisation that every
ingested prior now goes through (:func:`midrank_percentiles`), 0.0 is not
"unknown", it is *the worst possible score* — so defaulting to it actively
ranked uncovered residues as bad sites rather than as unmeasured ones, and a
patch was penalised for the predictor's coverage gap.

NaN propagates as "no information": :func:`~.base.rank_patches` aggregates over
the covered subset and reports ``n_covered``, so the join stays a LEFT join.
An inner join — dropping residues the prior misses — would silently shrink the
candidate set, which is the worst available failure for a tool whose entire
purpose is catching silent failures.
"""
def midrank_percentiles(
    scores: Mapping[ResidueKey, float],
) -> dict[ResidueKey, float]:
    """Within-target midrank percentiles in [0, 1]; ties share their mean rank.

    Every ingested prior goes through this before it reaches a score, because
    raw outputs from these tools are **incommensurable by construction**:
    DiscoTope-3.0's ``calibrated_score`` is z-like and unbounded, BepiPred's
    meaningful threshold is 0.1512, ScanNet's is a smoothed sigmoid. Averaging
    an unbounded z-score over a patch is not the same operation as averaging a
    probability, so the raw numbers cannot be blended, compared across backends,
    or thresholded with one constant.

    Percentiles are *within one target*, which is the only scope in which a rank
    is meaningful — a residue's percentile says "more epitope-like than 80% of
    this protein's residues", not anything about a different protein.

    Midrank rather than ordinal because ties are common (tools round, and some
    emit identical scores for whole loops) and breaking them arbitrarily would
    invent a ranking the predictor did not express.

    NaN inputs stay NaN and are excluded from the ranking, so an uncovered
    residue does not displace a covered one.
    """
    finite = {k: v for k, v in scores.items() if not math.isnan(v)}
    out: dict[ResidueKey, float] = {
        k: UNSCORED for k in scores if math.isnan(scores[k])
    }
    if not finite:
        return out
    if len(finite) == 1:
        # One value has no distribution to sit in; 0.5 says "no information
        # about where it ranks", where 1.0 would falsely claim it is the best.
        return {**out, **{k: 0.5 for k in finite}}

    ordered = sorted(finite.items(), key=lambda kv: kv[1])
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        midrank = (i + j) / 2.0  # 0-based mean rank of this tied block
        for k, _ in ordered[i : j + 1]:
            out[k] = midrank / (n - 1)
        i = j + 1
    return out
