# SPDX-License-Identifier: MIT
"""The default baseline predictor: four named features, hand-set weights.

Not a novel method and not presented as one — see :mod:`.base` for the full
positioning. Site ranking is published prior art; this exists so the package has
an interpretable default that needs no extra install, and so the downstream
assembly-aware filter has something concrete to be measured against.

The feature definitions and the geometry live in :mod:`.features`; this module
owns only the weights that combine them and the ranking pipeline around them.
Names are re-exported so ``from ...predict.geometric import X`` keeps working.

**The weights in :data:`DEFAULT_WEIGHTS` are not tuned, and on antibody epitopes
they are measurably wrong.** They are round numbers chosen by hand to express an
ordering we think is defensible for *designed minibinder sites*, and they have
never been fitted to any outcome. Measured on the benchmark's antibody epitopes
they score macro AUROC 0.5170, below a within-instance permutation null of
0.6056, because the epitope residues are *less* concave and *less* hydrophobic
than the surrounding surface and half the weight therefore pushes the wrong way.
See :mod:`.profiles` and ``docs/ranker-evaluation.md``.

Which weights to use is now a choice between named :class:`~.profiles.WeightProfile`
objects, each carrying its own provenance and its own honest
``n_outcomes_fitted``. The default is unchanged: :data:`~.profiles.DESIGNABILITY`,
the historical hand-set weights. Changing the default is a decision about what
this tool claims to rank, not a refactor, so it is not made here.

Tuning, when it happens, may only happen on a split declared as training data
before the fit, and never on anything the package is evaluated on — a ranker
tuned on its own test set reports its training error and nothing else.
:data:`~.profiles.ANTIBODY_EPITOPE` was fitted under that rule and records the
split, the counts and the date.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, Sequence

from ..checks.sasa import BurialProfile
from ..residue import ResidueKey
from ..structure import Target
from ..surface import EXPOSED_RELATIVE_SASA, Patch
from .base import (
    NMS_JACCARD_THRESHOLD,
    ScoredPatch,
    rank_patches,
    suppress_overlapping,
)
from .features import (
    ANCHOR_FALLBACK_COUNT,
    CONCAVITY_RADIUS_A,
    CONNECTIVITY_RADIUS_A,
    CONNECTIVITY_REFERENCE,
    DEGENERATE_NORMAL_A,
    HYDROPHOBIC_RESIDUES,
    Point,
    anchor_residues,
    assembly_context,
    concavity_feature,
    connectivity_feature,
    exposure_feature,
    hydrophobicity_feature,
    residue_names,
    residue_points,
)
from .profiles import (
    ANTIBODY_EPITOPE,
    DESIGNABILITY,
    EXPOSURE_ONLY,
    FEATURE_NAMES,
    PROFILES,
    WeightProfile,
    get_profile,
)

__all__ = [
    "CONCAVITY_RADIUS_A",
    "CONNECTIVITY_RADIUS_A",
    "CONNECTIVITY_REFERENCE",
    "DEGENERATE_NORMAL_A",
    "HYDROPHOBIC_RESIDUES",
    "ANCHOR_FALLBACK_COUNT",
    "DEFAULT_WEIGHTS",
    "FEATURE_NAMES",
    "WeightProfile",
    "DESIGNABILITY",
    "ANTIBODY_EPITOPE",
    "EXPOSURE_ONLY",
    "PROFILES",
    "get_profile",
    "Point",
    "residue_points",
    "residue_names",
    "assembly_context",
    "exposure_feature",
    "concavity_feature",
    "hydrophobicity_feature",
    "connectivity_feature",
    "anchor_residues",
    "GeometricPredictor",
]

DEFAULT_WEIGHTS: Mapping[str, float] = DESIGNABILITY.weights
"""Alias of :data:`~.profiles.DESIGNABILITY`'s weights. The same object, not a copy.

Kept as a name because it is the one part of this module third-party code is
likely to import. An alias rather than a second literal on purpose: two copies of
the same four numbers drift, and the copy that drifts is the one nobody reads.

Untuned, sums to 1.0, and **measurably wrong for antibody epitopes**. The
ordering was the assertion — reachable (exposure), then grippable (concavity),
then chemically willing (hydrophobicity), with compactness as a tie-breaker — and
on observed antibody epitopes two of those four terms have the wrong sign:
epitope residues are *less* concave and *less* hydrophobic than the rest of the
surface, so the 0.30 and 0.20 cancel most of the 0.40 and 0.10 and the result
(macro AUROC 0.5170) lands below a permutation null of 0.6056. The weights remain
unvalidated, separately, for the designed minibinder sites they were written for.
Full provenance in :data:`~.profiles.DESIGNABILITY`, measurement in
``docs/ranker-evaluation.md``.
"""

# A sentinel, not a default value. Identity-checked in __post_init__, so a
# caller who genuinely passes an empty mapping gets an empty mapping rather than
# silently inheriting the profile's weights.
_FROM_PROFILE: Mapping[str, float] = MappingProxyType({})


# ---------------------------------------------------------------------------
# The predictor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeometricPredictor:
    """The default, interpretable baseline. Weights are configuration.

    Args:
        name: recorded on every :class:`~.base.ScoredPatch` it produces.
        weights: per-feature weights, keyed by :data:`FEATURE_NAMES`. Left
            unset, they come from ``profile``. A key not in ``FEATURE_NAMES`` is
            rejected rather than ignored, because a typo'd weight that silently
            does nothing looks exactly like a weight that had no effect. A
            missing key means zero.
        profile: which named :class:`~.profiles.WeightProfile` to score with.
            Defaults to :data:`~.profiles.DESIGNABILITY` — the historical
            hand-set weights, unchanged, so that selecting a profile is opt-in
            and no existing caller's numbers move. Pass
            :data:`~.profiles.EXPOSURE_ONLY` or
            :data:`~.profiles.ANTIBODY_EPITOPE` for an antibody-like antigen;
            ``docs/ranker-evaluation.md`` has the comparison.

            Explicit ``weights`` override it, and then
            :attr:`n_outcomes_fitted` reports 0 whatever the profile says,
            because weights a caller supplied by hand are by definition not the
            ones that were fitted.
    """

    name: str = "geometric"
    weights: Mapping[str, float] = field(default_factory=lambda: _FROM_PROFILE)
    profile: WeightProfile = DESIGNABILITY

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(
                f"unknown feature weight(s) {sorted(unknown)}; "
                f"features are {list(FEATURE_NAMES)}"
            )
        if self.weights is _FROM_PROFILE:
            object.__setattr__(self, "weights", self.profile.weights)

    @property
    def n_outcomes_fitted(self) -> int:
        """How many measured binding outcomes the weights *in use* were fitted to.

        Zero for the default, and zero whenever ``weights`` was passed
        explicitly — an overridden weight vector inherits none of the profile's
        evidence, however the profile was obtained. Only weights taken from the
        profile report the profile's count.

        A property rather than :data:`~.base.N_OUTCOMES_FITTED`, which is a
        single package-wide zero and cannot be right for every profile at once
        now that :data:`~.profiles.ANTIBODY_EPITOPE` exists.
        """
        if self.weights is not self.profile.weights:
            return 0
        return self.profile.n_outcomes_fitted

    @property
    def weight_profile_name(self) -> str | None:
        """Name of the profile the weights in use actually came from, else ``None``.

        What a run record should report, and not the same thing as
        ``self.profile.name``: ``profile`` is the *requested* profile and stays
        set when ``weights`` overrides it, so reporting its name would attribute
        a ranking to weights that did not produce it. ``None`` means "weights
        supplied by hand", which is a different provenance claim from any named
        profile — including from ``designability``, whose name a caller would
        otherwise see after overriding every one of its numbers.

        Shares its identity test with :attr:`n_outcomes_fitted` so the two
        cannot disagree about whether an override happened.
        """
        if self.weights is not self.profile.weights:
            return None
        return self.profile.name

    def score_components(
        self, target: Target, profile: BurialProfile
    ) -> dict[ResidueKey, dict[str, float]]:
        """Weight-applied per-feature contributions for every profiled residue.

        Already multiplied by the weights so the values sum to the residue
        score. An unweighted breakdown would need the caller to re-apply the
        weights to interpret it, and a caller that used a different set would
        produce an explanation that did not match the ranking.
        """
        structure = assembly_context(target, profile)
        points = residue_points(structure)
        names = residue_names(structure)
        surface = [
            key
            for key, rel in profile.relative_sasa.items()
            if rel >= EXPOSED_RELATIVE_SASA
        ]

        out: dict[ResidueKey, dict[str, float]] = {}
        for key in profile.relative_sasa:
            raw = {
                "exposure": exposure_feature(key, profile),
                "concavity": concavity_feature(key, points),
                "hydrophobicity": hydrophobicity_feature(names.get(key, "UNK")),
                "connectivity": connectivity_feature(key, points, surface),
            }
            out[key] = {
                feature: self.weights.get(feature, 0.0) * value
                for feature, value in raw.items()
            }
        return out

    def score_residues(
        self, target: Target, profile: BurialProfile
    ) -> dict[ResidueKey, float]:
        """Weighted sum of the four features, per residue.

        Every residue in the profile is scored, not only the exposed ones, so
        that a patch built to a slightly different exposure cut-off still has a
        score for each of its residues. Burial is handled by the arithmetic
        rather than by exclusion: a buried residue scores near zero through
        :func:`exposure_feature`.
        """
        return {
            key: sum(components.values())
            for key, components in self.score_components(target, profile).items()
        }

    def rank(
        self,
        target: Target,
        profile: BurialProfile,
        patches: Sequence[Patch],
        *,
        aggregate: str = "mean",
        nms: bool = True,
        nms_threshold: float = NMS_JACCARD_THRESHOLD,
    ) -> list[ScoredPatch]:
        """Score, rank, deduplicate and annotate patches in one call.

        This is the entry point a CLI or a gate should use rather than wiring
        :func:`~.base.rank_patches` by hand, because it is what guarantees the
        three things that are easy to get wrong individually: the components
        breakdown is attached, near-duplicate patches are suppressed *before*
        anything positional is computed, and every result carries anchors with
        both the gateable mean and the report-only maximum.

        Args:
            nms: suppress near-duplicate patches. Default ``True``. Turning it
                off makes any rank, percentile or top-k window a partial
                statement about enumeration density — see
                :func:`~.base.suppress_overlapping`.
        """
        scores = self.score_residues(target, profile)
        components = self.score_components(target, profile)
        ranked = rank_patches(
            patches,
            scores,
            predictor_name=self.name,
            aggregate=aggregate,
            residue_components=components,
        )
        if nms:
            ranked = suppress_overlapping(ranked, nms_threshold)

        names = residue_names(assembly_context(target, profile))
        out: list[ScoredPatch] = []
        for scored in ranked:
            anchors = anchor_residues(scored.patch, profile, names)
            values = [
                scores[k] for k in anchors if k in scores and not math.isnan(scores[k])
            ]
            out.append(
                replace(
                    scored,
                    n_outcomes_fitted=self.n_outcomes_fitted,
                    anchors=anchors,
                    anchor_mean=(
                        sum(values) / len(values) if values else float("nan")
                    ),
                    anchor_max=max(values) if values else float("nan"),
                )
            )
        return out
