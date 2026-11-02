# SPDX-License-Identifier: MIT
"""The other direction: propose sites instead of checking one you already have.

``report.run_preflight`` answers "is this site real?". This module answers "which
sites are there?" — enumerate the target's surface patches, score them, and hand
back a ranking. It is library code rather than CLI code for the same reason
``run_preflight`` is: the pipeline has three places where a plausible-looking
mistake produces output that is wrong but not obviously wrong, and each needs to
be testable without going through a command line.

**One reference table, built once.** Relative SASA is an absolute area over a
per-residue-type reference maximum, so two profiles built against different
tables are in different units. Recomputing the table per context rescales every
denominator, and because the rescaled values stay in range and keep their
ordering, nothing in the output looks wrong — which is exactly why
``BurialProfile`` carries a ``reference_id`` at all. :func:`propose_sites` builds
one table and threads it through every measurement.

**Suppression before any window.** ``enumerate_patches`` grows one patch per seed
residue on purpose, so that a site is never missed for straddling an arbitrary
partition. The cost is near-duplicates, and a "top 10" taken before they are
collapsed is partly a statement about enumeration density rather than about the
sites. Non-maximum suppression therefore runs before the top-k, never after.

**``anchor_max`` is never thresholded.** It is reported for inspection and that
is all. On a maximum, one partly-occluded rim residue speaks for a whole patch,
which mass-kills surface anywhere near an oligomer contact; ``anchor_mean`` is
the gateable statistic. :meth:`ScoredPatch.to_dict` names the field
``anchor_max_do_not_threshold`` for the same reason, and nothing here sorts,
filters or cuts on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .checks.burial import (
    compute_burial,
    expand_assembly,
    reference_max_sasa,
    trim_to_neighbourhood,
)
from .predict import rank_patches, suppress_overlapping
from .structure import Target
from .surface import enumerate_patches

__all__ = [
    "CUSTOM_WEIGHTS",
    "ProposedSites",
    "propose_sites",
    "rank_candidates",
    "render_propose_text",
    "to_propose_record",
]


@dataclass
class ProposedSites:
    """A ranked candidate list, with the context it was measured in.

    The counts are kept separately because "rank 3 of 43" and "rank 3 of 105"
    are different claims, and only the suppressed figure is a statement about
    sites rather than about how densely we enumerated.
    """

    target_id: str
    input_filename: str
    chain: str
    assembly_id: str | None
    context: str
    predictor: str
    weight_profile: str | None
    """How the ranking was weighted. Three distinguishable answers.

    A profile name (``"designability"``, ``"antibody_epitope"``,
    ``"exposure_only"``) when the weights came from a named profile;
    ``CUSTOM_WEIGHTS`` when a caller supplied weights by hand, which inherit none
    of a profile's provenance; and ``None`` when the backend has no weights at
    all, as an external score file is read rather than reweighted.

    The last two are kept apart deliberately. Collapsing them to ``None`` — the
    first version of this field did — makes a hand-tuned geometric run
    indistinguishable in the record from a predictor that never had weights.

    Part of the record rather than of the invocation: two rankings of the same
    chain under ``designability`` and ``antibody_epitope`` differ, one of them is
    below chance on antibody epitopes, and a reader cannot tell which they are
    holding from the predictor name alone.
    """
    reference_id: str
    n_enumerated: int
    ranked: list[Any]

    @property
    def n_after_suppression(self) -> int:
        return len(self.ranked)

    def top(self, n: int) -> list[Any]:
        if n < 1:
            raise ValueError(f"top must be at least 1, got {n}")
        return self.ranked[:n]


CUSTOM_WEIGHTS = "custom"
"""Recorded in place of a profile name when weights were supplied by hand.

A name rather than ``None`` so the record distinguishes hand-typed weights from a
backend that has no weights to name. Read by a consumer comparing two runs, so it
is part of the output contract, not a display string.
"""


def _weight_profile_of(predictor: Any) -> str | None:
    """How ``predictor`` was weighted, for the record. See
    :attr:`ProposedSites.weight_profile`.

    ``hasattr`` rather than a ``getattr(..., None)`` default, because the default
    cannot tell "no weights to report" from "weights overridden" — both arrive as
    ``None`` and only one of them is a backend without weights.
    """
    if not hasattr(predictor, "weight_profile_name"):
        return None
    return predictor.weight_profile_name or CUSTOM_WEIGHTS


def rank_candidates(
    predictor: Any, target: Target, profile: Any, patches: Sequence[Any]
) -> list[Any]:
    """Rank patches, collapsing near-duplicates before anything positional.

    Prefers the predictor's own ``rank``, which the geometric backend documents
    as the entry point a caller should use: it is what attaches the component
    breakdown, suppresses near-duplicates at the right moment, and annotates
    anchors. The ``SitePredictor`` protocol only requires ``score_residues``, so
    a backend without ``rank`` — an external score file, say — gets the same two
    steps in the same order rather than silently skipping suppression.
    """
    if hasattr(predictor, "rank"):
        return predictor.rank(target, profile, patches)
    scores = predictor.score_residues(target, profile)
    ranked = rank_patches(
        patches, scores, predictor_name=getattr(predictor, "name", "unknown")
    )
    return suppress_overlapping(ranked)


def propose_sites(
    target: Target, predictor: Any, *, chain: str | None = None
) -> ProposedSites:
    """Enumerate, measure and rank the candidate sites on one chain.

    Args:
        target: loaded structure. To measure on a specific biological assembly,
            pass it through ``report.select_assembly`` first.
        predictor: a ``SitePredictor``, from ``predict.get``.
        chain: author chain id, or ``None`` for the first polymer chain.

    Raises:
        ValueError: if the entry has no polymer chain, or ``chain`` is not one of
            them. Falling back to a different chain would rank the wrong surface
            and say nothing about it.
    """
    chains = target.chain_ids
    if not chains:
        raise ValueError(
            f"{target.entry_id} has no polymer chain to propose sites on"
        )
    focus = chains[0] if chain is None else chain
    if focus not in chains:
        raise ValueError(
            f"chain {focus!r} is not in {target.entry_id}; its polymer chains "
            f"are {', '.join(chains)}"
        )

    # The single reference table. See the module docstring: a per-context
    # recompute is invisible in the output, which is what makes it dangerous.
    reference = reference_max_sasa(target.st)

    has_assembly = len(target.st.assemblies) > 0
    expanded = expand_assembly(target) if has_assembly else target.st
    # Trimmed before measuring, not after: 6F5J expands to 180 chains and SASA
    # over all of them is not a tractable calculation. Burial is local, so the
    # neighbourhood is also the correct scope, not merely the affordable one.
    trimmed = trim_to_neighbourhood(expanded, focus)
    profile = compute_burial(
        trimmed,
        context="assembly" if has_assembly else "chain",
        focus_chain=focus,
        reference=reference,
    )

    patches = enumerate_patches(trimmed, profile, chain=focus)
    ranked = rank_candidates(predictor, target, profile, patches)
    return ProposedSites(
        target_id=target.entry_id,
        input_filename=Path(target.path).name,
        chain=focus,
        assembly_id=(
            target.st.assemblies[0].name if has_assembly else None
        ),
        context=profile.context,
        predictor=getattr(predictor, "name", "unknown"),
        weight_profile=_weight_profile_of(predictor),
        reference_id=profile.reference_id,
        n_enumerated=len(patches),
        ranked=ranked,
    )


def to_propose_record(sites: ProposedSites, top: int) -> dict[str, Any]:
    """The JSON artifact: the ranking plus what it was measured against.

    Carries ``reference_id`` so two proposals can be told apart when they were
    scored on different denominator scales, and no absolute path — only the
    input's base name, matching the run record's rule.
    """
    shown = sites.top(top)
    return {
        "target_id": sites.target_id,
        "input_filename": sites.input_filename,
        "chain": sites.chain,
        "assembly_id": sites.assembly_id,
        "context": sites.context,
        "predictor": sites.predictor,
        "weight_profile": sites.weight_profile,
        "reference_id": sites.reference_id,
        "n_patches_enumerated": sites.n_enumerated,
        "n_after_suppression": sites.n_after_suppression,
        "n_shown": len(shown),
        "patches": [s.to_dict() for s in shown],
    }


def _anchor_text(value: float | None) -> str:
    """Format ``anchor_mean``, which is NaN when no anchor was covered.

    NaN prints as "-" rather than "nan": the distinction the reader needs is
    "not measured", and ``nan`` in a score column invites it being read as zero.
    """
    if value is None or value != value:
        return "     -"
    return f"{value:6.3f}"


def render_propose_text(sites: ProposedSites, top: int) -> str:
    """The ranked table, returned rather than printed.

    Shows ``anchor_mean`` and not ``anchor_max`` — see the module docstring. Both
    patch counts are stated so a rank can be read against the right denominator.
    No colour or emoji: this is read in CI logs and pasted into notebooks.
    """
    shown = sites.top(top)
    where = f"{sites.target_id} chain {sites.chain}"
    if sites.assembly_id is not None:
        where += f", biological assembly {sites.assembly_id}"
    # The profile is named here and not only in the JSON because this table is
    # what gets pasted into a notebook or an issue. Two profiles rank the same
    # chain differently, one of them is below chance on antibody epitopes, and
    # the suppression count printed on the next line is itself profile-dependent
    # — NMS drops patches in score order. A table carrying profile-dependent
    # numbers has to say which profile produced them.
    first = f"{where} — {sites.predictor} predictor"
    if sites.weight_profile is not None:
        first += f", {sites.weight_profile} weights"
    lines = [
        first,
        f"{sites.n_enumerated} candidate patches, {sites.n_after_suppression} "
        f"after overlap suppression; showing {len(shown)}",
        "",
    ]
    if not shown:
        lines.append("(no candidate patches)")
        return "\n".join(lines) + "\n"

    header = (
        f"{'rank':>4}  {'score':>8}  {'size':>4}  {'rSASA':>6}  "
        f"{'anchor':>6}  residues"
    )
    lines.extend([header, "-" * len(header)])
    for position, scored in enumerate(shown, start=1):
        lines.append(
            f"{position:>4}  {scored.score:8.4f}  {len(scored.residues):>4}  "
            f"{scored.patch.mean_relative_sasa:6.3f}  "
            f"{_anchor_text(scored.anchor_mean)}  "
            f"{','.join(str(k) for k in scored.residues)}"
        )
    return "\n".join(lines) + "\n"
