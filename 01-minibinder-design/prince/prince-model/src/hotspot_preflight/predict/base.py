# SPDX-License-Identifier: MIT
"""The predictor interface, and patch-level aggregation of residue scores.

Scope, stated plainly because it is easy to overread: **this package proposes
candidate sites and nothing here is a novel predictor.** Ranking surface
patches by how binder-like or epitope-like they look is published prior art —
Site4Drug (arXiv:2606.01816), SurfDiff, DiscoTope-3.0, SEMA, ScanNet, PeSTo and
MaSIF-site all do it, most of them with trained models and all of them with
more validation than we have. We make no claim to improve on any of them.

What this stage is for:

1. An honest, interpretable **baseline** so the package is usable without
   installing anything else — four named geometric features, hand-set weights,
   no learned parameters anywhere.
2. A **plugin host**, so one of those published predictors can be the backend
   instead (:class:`~hotspot_preflight.predict.external.ExternalPredictor` for
   score files, :mod:`~hotspot_preflight.predict.registry` for installed
   packages).

The project's actual contribution is downstream: the assembly-aware filter that
catches sites which are only exposed because of a crop or an isolated chain. The
measurable claim is therefore *how much that filter improves whichever predictor
you plug in here* — a delta, measured per backend. It is not "our ranker is
good". Keeping the predictor swappable is what makes that delta measurable at
all.

No trained model, no learned embedding and no neural network lives in this
package. Weights are configuration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Protocol, Sequence

from ..residue import ResidueKey

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..checks.sasa import BurialProfile
    from ..structure import Target
    from ..surface import Patch

__all__ = [
    "AGGREGATES",
    "LINEAR_AGGREGATES",
    "NMS_JACCARD_THRESHOLD",
    "EXTERNAL_PRIOR_DEFAULT_WEIGHT",
    "N_OUTCOMES_FITTED",
    "ScoredPatch",
    "SitePredictor",
    "provenance",
    "jaccard",
    "suppress_overlapping",
    "rank_patches",
]

NMS_JACCARD_THRESHOLD = 0.50
"""Residue-Jaccard at or above which two patches are the same candidate.

:func:`~hotspot_preflight.surface.enumerate_patches` grows one patch per seed
residue, so neighbouring seeds produce heavily overlapping patches — 114 of them
on one 393-residue chain. Left in, every percentile, tier and top-k window is
partly a statement about how many near-duplicates happened to surround a patch
rather than about the patch, so a rank of "6 of 114" is not interpretable.
:func:`suppress_overlapping` collapses them before any of those are computed.
"""

EXTERNAL_PRIOR_DEFAULT_WEIGHT = 0.0
"""Weight given to an external predictor when none is explicitly requested.

**Zero, as a hard requirement, not a conservative default.** The tool must
produce a complete ranking from a structure file alone: no external score file,
no GPU, no Docker, no web-server submission, no account. A high-school team
cannot be blocked on a DTU web form, and a default that silently needed one
would make the baseline unusable for exactly the users it is for.
"""

N_OUTCOMES_FITTED = 0
"""How many measured binding outcomes any weight in this package was fitted to.

Zero, stated unconditionally in :func:`provenance` and in every
:meth:`ScoredPatch.to_dict`. Not a placeholder and not a default to be updated
when results arrive — if a weight is ever fitted, that is a different artifact
with a declared training split, and this number is how a reader tells the two
apart. Saying this plainly is worth more than any accuracy figure this baseline
could claim.
"""


def provenance() -> dict[str, Any]:
    """Honesty block for a run record. Emitted unconditionally.

    Every field here is a statement about *this package*, not about a run, so
    it is safe to emit before anything is computed and it cannot be made to
    say something flattering by choice of input.
    """
    return {
        "n_outcomes_fitted": N_OUTCOMES_FITTED,
        "weights_tuned": False,
        "trained_model": False,
        "learned_embeddings": False,
        "external_prior_default_weight": EXTERNAL_PRIOR_DEFAULT_WEIGHT,
        "site_ranking_is_prior_art": True,
        "prior_art": [
            "Site4Drug arXiv:2606.01816", "SurfDiff", "DiscoTope-3.0",
            "SEMA", "ScanNet", "PeSTo", "MaSIF-site",
        ],
        "contribution": (
            "the downstream assembly-aware filter, measured as a delta over "
            "whichever predictor is plugged in"
        ),
    }

AGGREGATES = ("mean", "max", "sum")
"""Ways to turn per-residue scores into one patch score."""

LINEAR_AGGREGATES = frozenset({"mean", "sum"})
"""The aggregates under which ``sum(components) == score`` holds exactly.

``max`` picks a different residue for each feature, so its component breakdown
describes the patch but does not add up to the patch score. Callers that rely on
the additive identity — a stacked-bar explanation, say — must use a linear
aggregate, and :func:`rank_patches` records which one was used so they can tell.
"""


@dataclass(frozen=True)
class ScoredPatch:
    """One candidate site with its score and the reasons behind it.

    Args:
        patch: the surface patch, from
            :func:`hotspot_preflight.surface.enumerate_patches`.
        score: the aggregated patch score. Higher is a better candidate. The
            scale is the predictor's own and is comparable only within one
            predictor on one target — never across backends.
        components: per-feature contributions, already weight-applied, so a
            reader can see *why* a patch ranked where it did rather than being
            handed one opaque number. Empty when the predictor supplies no
            breakdown (an external score file, for instance, is one number).
        predictor: name of the backend that produced the score, recorded so a
            run record cannot be mistaken for having come from a different one.
        n_covered: how many of the patch's residues the predictor actually
            scored. Below ``len(residues)`` whenever an external prior has
            coverage gaps, and reported rather than inferred so a thin patch
            score is distinguishable from a confident one.
        anchors: the residues a gate should threshold on, if the predictor
            identified them. See
            :func:`~hotspot_preflight.predict.geometric.anchor_residues`.
        anchor_mean: mean score over :attr:`anchors` — the statistic a gate or
            a delta must read.
        anchor_max: max score over :attr:`anchors`, reported for inspection.
            **Do not threshold on it**: on a max, one partly-occluded rim
            residue kills an otherwise clean patch, which mass-kills surface
            anywhere near an oligomer contact.
    """

    patch: "Patch"
    score: float
    components: Mapping[str, float] = field(default_factory=dict)
    predictor: str = "unknown"
    n_covered: int | None = None
    anchors: tuple[ResidueKey, ...] = ()
    anchor_mean: float | None = None
    anchor_max: float | None = None
    n_outcomes_fitted: int = 0

    @property
    def residues(self) -> tuple[ResidueKey, ...]:
        return self.patch.residues

    @property
    def coverage(self) -> float:
        """Fraction of the patch's residues the predictor scored."""
        if self.n_covered is None or not self.patch.residues:
            return 1.0
        return self.n_covered / len(self.patch.residues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "predictor": self.predictor,
            "score": _jsonable(self.score),
            "components": {k: _jsonable(v) for k, v in self.components.items()},
            "residues": [str(k) for k in self.patch.residues],
            "n_residues": len(self.patch.residues),
            "n_covered": self.n_covered,
            "anchors": [str(k) for k in self.anchors],
            # Both are emitted, but only anchor_mean is a gateable quantity.
            "anchor_mean": _jsonable(self.anchor_mean),
            "anchor_max_do_not_threshold": _jsonable(self.anchor_max),
            "area": round(self.patch.area, 2),
            "mean_relative_sasa": round(self.patch.mean_relative_sasa, 4),
            "centroid": [round(c, 3) for c in self.patch.centroid],
            "n_outcomes_fitted": self.n_outcomes_fitted,
        }


class SitePredictor(Protocol):
    """A backend that scores residues for how good a binder site they are.

    Residue-level rather than patch-level on purpose: every published predictor
    in this space emits per-residue scores, so a thin adapter is enough to plug
    one in, and the patch definition stays ours rather than being whatever the
    backend happened to use.
    """

    name: str

    def score_residues(
        self, target: "Target", profile: "BurialProfile"
    ) -> dict[ResidueKey, float]:
        """Score residues of ``target`` in the context ``profile`` measured.

        The profile fixes the structural context — assembly, isolated chain or
        crop — and a predictor must not quietly measure a different one, since
        comparing scores computed in different contexts is the exact error this
        package exists to catch.
        """
        ...


def _jsonable(value: float | None) -> float | None:
    """Round for output, mapping NaN to ``None``.

    JSON has no NaN; ``json.dumps`` emits the literal ``NaN``, which is invalid
    JSON that many parsers accept silently and others reject at read time. An
    explicit null says "not measured" in a form every consumer agrees on.
    """
    if value is None or math.isnan(value):
        return None
    return round(value, 6)


def _reduce(values: Sequence[float], aggregate: str) -> float:
    """Aggregate, skipping NaN. All-NaN reduces to NaN.

    Skipping rather than propagating because NaN here means "this residue was
    not covered by the prior", and one uncovered residue must not erase a patch
    that is otherwise well measured — that would turn a coverage gap into a
    structural verdict. All-NaN genuinely has no information, so it stays NaN
    and :func:`_rank_key` sorts it last.
    """
    present = [v for v in values if not math.isnan(v)]
    if not present:
        return float("nan")
    if aggregate == "mean":
        return sum(present) / len(present)
    if aggregate == "max":
        return max(present)
    return sum(present)


def _canonical_residue_order(
    residues: Iterable[ResidueKey],
) -> tuple[tuple[str, int, str], ...]:
    """Sorted primitive form of a residue set, for deterministic tie-breaking.

    Primitives rather than the keys themselves so the comparison can never
    depend on :class:`ResidueKey` growing a field or changing its ``order``.
    """
    return tuple(
        sorted((k.auth_asym_id, k.auth_seq_id, k.icode) for k in residues)
    )


_RankKey = tuple[int, float, float, tuple[tuple[str, int, str], ...]]


def _rank_key(scored: ScoredPatch) -> _RankKey:
    """Descending score, then descending area, then canonical residue order.

    Area breaks score ties because between two equally scored patches the
    larger one gives a design tool more to grip. The residue order is the final
    tie-break purely so the output is reproducible: two patches identical in
    score and area must still come back in the same order on every run, or
    nothing downstream — run records, the benchmark, test assertions — is
    comparable between runs.
    """
    # NaN cannot be ordered, and `-nan` compares false against everything,
    # which would make sort order depend on input order. An explicit leading
    # flag puts every unscorable patch after every scored one, in canonical
    # order among themselves.
    unscorable = math.isnan(scored.score)
    return (
        1 if unscorable else 0,
        0.0 if unscorable else -scored.score,
        -scored.patch.area,
        _canonical_residue_order(scored.patch.residues),
    )


def rank_patches(
    patches: Sequence["Patch"],
    residue_scores: Mapping[ResidueKey, float],
    *,
    predictor_name: str,
    aggregate: str = "mean",
    residue_components: Mapping[ResidueKey, Mapping[str, float]] | None = None,
) -> list[ScoredPatch]:
    """Aggregate residue scores onto patches and rank them, best first.

    ``mean`` is the default rather than ``sum`` because a sum rewards large
    patches for being large, which would make the ranking a proxy for patch size
    instead of for site quality.

    Args:
        patches: candidate patches, from
            :func:`hotspot_preflight.surface.enumerate_patches`.
        residue_scores: a score for **every** residue in every patch.
        predictor_name: recorded on each result.
        aggregate: one of :data:`AGGREGATES`.
        residue_components: optional per-residue feature breakdown. Aggregated
            feature by feature with the same reduction, so under a linear
            aggregate (:data:`LINEAR_AGGREGATES`) the components of a result sum
            to its score.

    Raises:
        ValueError: on an unknown aggregate, or an empty patch — a patch with no
            residues has no definable score and silently dropping it would make
            the returned count disagree with the input count.
        KeyError: if any patch residue has no score. Filling a gap with zero
            would quietly rank a patch low for a reason that is a bookkeeping
            failure rather than a property of the structure, and the most likely
            cause is a residue-numbering mismatch between the two inputs — which
            is precisely the class of silent error this package is about.
    """
    if aggregate not in AGGREGATES:
        raise ValueError(f"aggregate must be one of {AGGREGATES}, got {aggregate!r}")

    missing: list[ResidueKey] = []
    for patch in patches:
        if not patch.residues:
            raise ValueError(
                "a patch with no residues cannot be scored; "
                "enumerate_patches should never emit one"
            )
        for key in patch.residues:
            if key not in residue_scores:
                missing.append(key)
    if missing:
        shown = ", ".join(str(k) for k in sorted(set(missing))[:5])
        raise KeyError(
            f"{len(set(missing))} patch residue(s) have no score from "
            f"{predictor_name!r} (e.g. {shown}). The patches and the scores "
            f"were built from different residue sets — check that both came "
            f"from the same structure and the same numbering scheme."
        )

    out: list[ScoredPatch] = []
    for patch in patches:
        keys = patch.residues
        score = _reduce([residue_scores[k] for k in keys], aggregate)
        components: dict[str, float] = {}
        if residue_components is not None:
            names = sorted(
                {name for k in keys for name in residue_components.get(k, {})}
            )
            components = {
                name: _reduce(
                    [residue_components.get(k, {}).get(name, 0.0) for k in keys],
                    aggregate,
                )
                for name in names
            }
        out.append(
            ScoredPatch(
                patch=patch,
                score=score,
                components=components,
                predictor=predictor_name,
                n_covered=sum(
                    1 for k in keys if not math.isnan(residue_scores[k])
                ),
            )
        )

    out.sort(key=_rank_key)
    return out


def jaccard(a: Iterable[ResidueKey], b: Iterable[ResidueKey]) -> float:
    """Residue-set Jaccard index, ``|a & b| / |a | b|``."""
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def suppress_overlapping(
    ranked: Sequence[ScoredPatch],
    threshold: float = NMS_JACCARD_THRESHOLD,
) -> list[ScoredPatch]:
    """Greedy non-maximum suppression over residue-Jaccard overlap.

    Walks the patches best-first and keeps one only if it overlaps every
    already-kept patch by less than ``threshold``, so the higher-scoring member
    of each cluster of near-duplicates survives.

    This must run **before** any percentile, tier or top-k window is computed.
    :func:`~hotspot_preflight.surface.enumerate_patches` grows one patch per
    seed residue by design — that is what stops a site being missed because it
    straddles an arbitrary partition — but it means a rank is otherwise diluted
    by however many near-duplicates happened to surround the patch, and "rank 6
    of 114" becomes partly a statement about the enumeration density rather
    than about the site. Measured on 6F5J chain C, suppression at 0.50 takes
    114 patches to 49.

    Args:
        ranked: patches in the order :func:`rank_patches` returned them. The
            input order *is* the priority, so passing an unranked list would
            keep arbitrary members of each cluster.
        threshold: Jaccard at or above which two patches are one candidate.

    Raises:
        ValueError: if ``threshold`` is outside (0, 1]. Zero would suppress
            everything after the first patch, which reads as "only one site
            found".
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError(
            f"threshold must be in (0, 1], got {threshold}; 0 would suppress "
            f"every patch after the first"
        )
    kept: list[ScoredPatch] = []
    for candidate in ranked:
        if all(
            jaccard(candidate.patch.residues, k.patch.residues) < threshold
            for k in kept
        ):
            kept.append(candidate)
    return kept
