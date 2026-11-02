# SPDX-License-Identifier: MIT
"""The four interpretable features, and the geometry they are measured on.

Split from :mod:`.geometric` so the feature definitions sit apart from the
weighting that combines them: a reader checking *what* concavity means should
not have to scroll past the predictor, and a reader checking *how much* it
counts should not have to scroll past the trigonometry.

Everything here is arithmetic over coordinates and solvent accessibility. There
is no trained model, no learned embedding and no neural network. Each feature is
a module-level function with its own test and an asserted value on a hand-built
geometry, so a reader can check the definition rather than trust it.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

import gemmi

from ..checks.burial import expand_assembly, trim_to_neighbourhood
from ..checks.sasa import BurialProfile, _heavy_atoms, _is_amino_acid
from ..residue import ResidueKey
from ..structure import Target, _icode
from ..surface import EXPOSED_RELATIVE_SASA, Patch

__all__ = [
    "CONCAVITY_RADIUS_A",
    "CONNECTIVITY_RADIUS_A",
    "CONNECTIVITY_REFERENCE",
    "DEGENERATE_NORMAL_A",
    "HYDROPHOBIC_RESIDUES",
    "Point",
    "residue_points",
    "residue_names",
    "assembly_context",
    "exposure_feature",
    "concavity_feature",
    "hydrophobicity_feature",
    "connectivity_feature",
    "ANCHOR_FALLBACK_COUNT",
    "anchor_residues",
    "GeometricPredictor",
]

ANCHOR_FALLBACK_COUNT = 3
"""How many residues become anchors when a patch has no exposed hydrophobics.

Three because that is the smallest set whose mean is not simply the maximum,
and because RFdiffusion's own guidance is 3-6 hotspots — a gate reading fewer
than three residues is reading a single residue with extra steps.
"""

Point = tuple[float, float, float]

CONCAVITY_RADIUS_A = 10.0
"""Neighbourhood radius for :func:`concavity_feature`, angstroms.

Chosen to span roughly the footprint a minibinder helix presses against — a few
residues in every direction — rather than a single side chain's contact shell.
"""

CONNECTIVITY_RADIUS_A = 8.0
"""Radius at which two surface residues count as graph neighbours, angstroms."""

CONNECTIVITY_REFERENCE = 8.0
"""Surface-neighbour count that saturates :func:`connectivity_feature` at 1.0.

Eight is about what a residue in the middle of an open face has within 8 A on a
globular protein; a residue on a thin ridge or an isolated spike has fewer.
"""

DEGENERATE_NORMAL_A = 1e-6
"""Below this, the local normal has no defined direction and concavity is 0.0."""

HYDROPHOBIC_RESIDUES = frozenset({
    "ALA", "VAL", "LEU", "ILE", "PRO", "PHE", "MET", "TRP", "CYS", "TYR",
})
"""Residue types counted as hydrophobic.

A declared choice, not a derived one. ALA/VAL/LEU/ILE/PRO/PHE/MET/TRP are
uncontroversially nonpolar; CYS and TYR are borderline on every hydropathy scale
and are included here because both are frequent and productive at designed
interfaces. MSE (selenomethionine) is deliberately absent: it is a
crystallographic substitute for MET, and a site whose hydrophobicity depends on
which experimental trick was used to phase the structure is not a real signal.
"""




# ---------------------------------------------------------------------------
# Geometry extraction
# ---------------------------------------------------------------------------


def residue_points(structure: gemmi.Structure) -> dict[ResidueKey, Point]:
    """Heavy-atom centroid of each amino-acid residue, as a plain 3-tuple.

    The centroid rather than CA because CA sits on the backbone, several
    angstroms behind the surface a binder actually touches, and a normal built
    from backbone positions points somewhere other than the side-chain face.

    Plain tuples rather than :class:`gemmi.Position` so the feature functions are
    pure arithmetic and can be tested on hand-written coordinates with no
    structure file involved.
    """
    out: dict[ResidueKey, Point] = {}
    for chain in structure[0]:
        for res in chain:
            if not _is_amino_acid(res):
                continue
            atoms = _heavy_atoms(res)
            if not atoms:
                continue
            n = float(len(atoms))
            key = ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode))
            out[key] = (
                sum(a.pos.x for a in atoms) / n,
                sum(a.pos.y for a in atoms) / n,
                sum(a.pos.z for a in atoms) / n,
            )
    return out


def residue_names(structure: gemmi.Structure) -> dict[ResidueKey, str]:
    """Three-letter residue type per residue key."""
    return {
        ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode)): res.name
        for chain in structure[0]
        for res in chain
        if _is_amino_acid(res)
    }


def assembly_context(target: Target, profile: BurialProfile) -> gemmi.Structure:
    """Coordinates in the same structural context ``profile`` was measured in.

    Rebuilt rather than carried on the profile because
    :class:`~hotspot_preflight.checks.sasa.BurialProfile` holds numbers, not
    atoms. Getting this wrong is the whole failure mode the package is about: a
    concavity measured on the isolated chain next to an exposure measured on the
    assembly would describe a protein that does not exist.

    Falls back to the asymmetric unit only when the entry declares no assembly,
    which is also the one case where
    :func:`~hotspot_preflight.checks.burial.check_burial` emits
    ``NO_ASSEMBLY_DEFINED`` — so the reduced confidence is already reported
    rather than hidden here.
    """
    if not target.st.assemblies:
        return target.st
    expanded = expand_assembly(target)
    focus = profile.parameters.get("focus_chain")
    if focus is not None:
        return trim_to_neighbourhood(expanded, focus)
    return expanded


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def exposure_feature(key: ResidueKey, profile: BurialProfile) -> float:
    """Relative solvent accessibility, clamped to [0, 1].

    Read from the profile, which the burial check computes **on the biological
    assembly**, and that is the point of this feature rather than an incidental
    detail: a residue that looks open on the isolated chain and is covered by a
    partner chain in the real multimer must score 0 here, because a binder
    cannot reach it. Measured on the isolated chain this feature would actively
    promote unusable sites.

    Clamped because relative SASA legitimately exceeds 1.0 on a freshly cut crop
    face (the denominator is the most exposed instance in the structure, see
    :func:`~hotspot_preflight.checks.sasa.reference_max_sasa`). Letting that
    through would let a crop artifact outrank every real site.

    A residue absent from the profile scores 0.0: absent means unmodelled or
    outside the measured chain, and neither is a site.
    """
    # Do NOT remove the min(). Without it this stage would rank crop artifacts
    # ABOVE real sites, because a cut face scores above 1.0 while the best
    # genuine surface tops out at 1.0 — the proposal half of the tool would
    # systematically prefer the exact pathology the burial check exists to
    # kill, and the symptom (top patches clustering on crop boundaries) reads
    # as a conceptual failure rather than one missing call. Pinned by
    # test_predict.py, in the test named
    # test_the_exposure_clamp_stops_a_crop_artifact_outranking_a_real_site
    return min(profile.relative_sasa.get(key, 0.0), 1.0)


def _distance(a: Point, b: Point) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def concavity_feature(
    key: ResidueKey,
    points: Mapping[ResidueKey, Point],
    radius: float = CONCAVITY_RADIUS_A,
) -> float:
    """Fraction of nearby residues that sit *outside* the local tangent plane.

    Definition, exactly:

    1. ``p`` is the residue's heavy-atom centroid; ``N`` is every other residue
       in ``points`` whose centroid is within ``radius`` of ``p``.
    2. The outward normal is ``n = normalise(p - centroid(N))`` — the direction
       away from the local mass. Degenerate (``|p - centroid(N)| <``
       :data:`DEGENERATE_NORMAL_A`) or empty ``N`` returns 0.0.
    3. The feature is the fraction of ``q`` in ``N`` with
       ``dot(q - p, n) > 0``: neighbours lying on the solvent side of the plane
       through ``p`` perpendicular to ``n``.

    What that measures: a residue on the floor of a groove has the groove's
    walls rising past its own tangent plane, so those wall residues count and
    the fraction is positive. A residue on a protruding knob has every
    neighbour behind it and scores 0.0. A residue on a flat face also scores
    0.0, because in-plane neighbours give ``dot == 0`` — so this feature
    separates *enclosed* from *not enclosed*, and does **not** distinguish flat
    from protruding. :func:`exposure_feature` carries that distinction.

    Counting residues and not atoms keeps the feature at the scale a binder
    interacts at and keeps it cheap enough to run over every surface residue of
    a trimmed capsid neighbourhood.

    **Why the baseline weights concavity at all is a design hypothesis we have
    not validated, not an established result.** The reasoning is that
    minibinders are usually rigid helical bundles that need a pocket or groove
    to grip, whereas antibody epitopes skew flat and protruding — so a ranker
    meant for binder design should disagree with an epitope predictor here, and
    concavity is where that disagreement would live. We have run no experiment
    that confirms this, and the published epitope predictors this package can
    host instead were trained on real labels. Treat the weight as a stated
    prior, and if it is ever tested and found wrong, lower it.
    """
    if key not in points:
        return 0.0
    p = points[key]
    neighbours = [
        q
        for other, q in points.items()
        if other != key and _distance(p, q) <= radius
    ]
    if not neighbours:
        return 0.0

    n = float(len(neighbours))
    centre = (
        sum(q[0] for q in neighbours) / n,
        sum(q[1] for q in neighbours) / n,
        sum(q[2] for q in neighbours) / n,
    )
    normal = (p[0] - centre[0], p[1] - centre[1], p[2] - centre[2])
    length = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    if length < DEGENERATE_NORMAL_A:
        return 0.0
    unit = (normal[0] / length, normal[1] / length, normal[2] / length)

    outside = sum(
        1
        for q in neighbours
        if (q[0] - p[0]) * unit[0]
        + (q[1] - p[1]) * unit[1]
        + (q[2] - p[2]) * unit[2]
        > 0.0
    )
    return outside / len(neighbours)


def hydrophobicity_feature(resname: str) -> float:
    """1.0 for a hydrophobic residue type, 0.0 otherwise.

    Binary rather than a graded hydropathy scale so that the patch-level mean
    is literally the hydrophobic fraction of the patch — a number a reader can
    recompute by counting residues, which a weighted Kyte-Doolittle average is
    not. The membership set is :data:`HYDROPHOBIC_RESIDUES`.

    An unrecognised type — a modified or exotic residue — scores 0.0 rather
    than raising. Calling it non-hydrophobic understates the patch, which
    understates the site, and understating fails safe.
    """
    return 1.0 if resname.upper() in HYDROPHOBIC_RESIDUES else 0.0


def connectivity_feature(
    key: ResidueKey,
    points: Mapping[ResidueKey, Point],
    surface_keys: Iterable[ResidueKey],
    radius: float = CONNECTIVITY_RADIUS_A,
    reference: float = CONNECTIVITY_REFERENCE,
) -> float:
    """Surface-neighbour count within ``radius``, over ``reference``, capped at 1.

    The neighbour graph is over *surface* residues only, so this measures
    whether the residue sits inside a broad contiguous face or on a narrow
    ridge. A design tool given a site made of surface residues that happen to be
    near each other in sequence but spread thin in space has nothing to bind
    across; the mean of this feature over a patch is the patch's compactness.

    Capped rather than unbounded so one unusually crowded residue cannot
    dominate a patch mean — past :data:`CONNECTIVITY_REFERENCE` neighbours the
    face is already open and more neighbours say nothing further.
    """
    if key not in points:
        return 0.0
    p = points[key]
    count = sum(
        1
        for other in surface_keys
        if other != key and other in points and _distance(p, points[other]) <= radius
    )
    return min(count / reference, 1.0)


def anchor_residues(
    patch: Patch,
    profile: BurialProfile,
    names: Mapping[ResidueKey, str],
    *,
    fallback_count: int = ANCHOR_FALLBACK_COUNT,
) -> tuple[ResidueKey, ...]:
    """The residues a gate or a delta should threshold on, as a mean.

    Anchors are the patch's **exposed hydrophobic** residues — exposed at or
    above :data:`~hotspot_preflight.surface.EXPOSED_RELATIVE_SASA` on the
    assembly, and hydrophobic by :data:`HYDROPHOBIC_RESIDUES`. Those are the
    residues a designed interface actually grips, so they are what a verdict
    about the site should rest on.

    When a patch has none — a polar site, which is legitimate — the fallback is
    the ``fallback_count`` residues with the highest assembly relative SASA, so
    every patch has anchors and no patch is silently ungateable.

    **Threshold on the mean over these, never on the per-patch maximum.** On a
    maximum, one partly-occluded rim residue is enough to kill a patch that is
    clean everywhere else, which mass-kills surface anywhere near an oligomer
    contact — and on a large assembly that is most of the surface. The maximum
    is still worth reporting, and :class:`~.base.ScoredPatch` carries it as
    ``anchor_max``, but it is named ``anchor_max_do_not_threshold`` in output
    for a reason.

    Returned in canonical residue order, so the anchor set is reproducible.
    """
    if fallback_count < 1:
        raise ValueError(f"fallback_count must be at least 1, got {fallback_count}")

    hydrophobic = [
        key
        for key in patch.residues
        if profile.relative_sasa.get(key, 0.0) >= EXPOSED_RELATIVE_SASA
        and hydrophobicity_feature(names.get(key, "UNK")) > 0.0
    ]
    if hydrophobic:
        return tuple(sorted(hydrophobic))

    by_exposure = sorted(
        patch.residues,
        key=lambda k: (-profile.relative_sasa.get(k, 0.0), k),
    )
    return tuple(sorted(by_exposure[:fallback_count]))
