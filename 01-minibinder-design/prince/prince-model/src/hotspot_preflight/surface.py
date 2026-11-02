# SPDX-License-Identifier: MIT
"""Surface patches: the shapes on a protein that a binder could actually cover.

A hotspot list is a claim about *geometry*, not just about residues. A binder
of 60-100 residues presents one face, roughly 15-25 A across, and contacts one
contiguous patch of target surface. Three residues on opposite sides of a
domain are each individually fine and collectively meaningless — no designed
protein can touch them all. Nothing in a design tool checks this: RFdiffusion
accepts any hotspot list, hallucinates a backbone that satisfies as much of it
as it can, and reports confident scores for the result.

So this module answers two questions about coordinates and nothing else:

* **Which residues are on the surface at all?** Read off a
  :class:`~hotspot_preflight.checks.sasa.BurialProfile`, so exposure is
  measured once, under pinned parameters, in whatever structural context the
  caller chose. This module never computes SASA itself.
* **Which sets of them form one patch?** A neighbour graph over heavy atoms,
  grown outward from each exposed residue.

It holds no verdicts. :mod:`hotspot_preflight.checks.patch` owns those.

One hazard dominates the implementation. ``gemmi.NeighborSearch`` applies
crystal symmetry when it is given a real unit cell, so a residue's "neighbours"
come to include lattice copies — and a patch grown through a crystal contact is
a site that does not exist in solution. Every search here is therefore built
with an empty :class:`gemmi.UnitCell`; see :func:`_neighbour_search`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

import gemmi

from .residue import ResidueKey
from .structure import Target, _icode

if TYPE_CHECKING:  # pragma: no cover - annotations only
    # Type-only, so this module has no runtime dependency on ``checks/``. It
    # reads a profile it is handed; it never builds one, and keeping the import
    # out of the runtime path is what makes that structural rather than a
    # convention someone could quietly break.
    from .checks.sasa import BurialProfile

__all__ = [
    "EXPOSED_RELATIVE_SASA",
    "PATCH_MIN_RESIDUES",
    "PATCH_MAX_RESIDUES",
    "PATCH_RADIUS_A",
    "NEIGHBOUR_CUTOFF_A",
    "Patch",
    "surface_residues",
    "residue_centroid",
    "neighbour_graph",
    "enumerate_patches",
    "patch_diameter",
    "patch_contiguous",
    "connected_components",
]

EXPOSED_RELATIVE_SASA = 0.20
"""Relative SASA at or above which a residue counts as surface.

Higher than :data:`~hotspot_preflight.checks.burial.BURIED_RELATIVE_SASA` (0.05)
on purpose, and the two are not interchangeable. 0.05 answers "is a binder
physically unable to reach this?" — a KILL, so it must be conservative. 0.20
answers "would I seed a patch here?" — a shortlist, so it should be selective.
A residue at 0.10 is reachable but is not a face worth aiming a campaign at.
"""

PATCH_MIN_RESIDUES = 3
"""Below this there is not enough surface to call it a patch, and it matches the
lower end of RFdiffusion's own hotspot recommendation."""

PATCH_MAX_RESIDUES = 12
"""A minibinder interface buries on the order of 10-15 target residues; beyond
that the set describes more surface than one small binder can cover."""

PATCH_RADIUS_A = 10.0
"""Growth radius around a seed residue's centroid, so a patch spans at most
20 A — about the width of the face a minibinder presents."""

NEIGHBOUR_CUTOFF_A = 8.0
"""Default heavy-atom distance at which two residues are adjacent on the
surface. Wider than a contact distance (~5 A) because surface residues need not
touch to be part of the same face; two side chains 8 A apart are both inside the
footprint of a single binder helix."""


@dataclass(frozen=True)
class Patch:
    """One candidate surface patch.

    Args:
        residues: the patch members, sorted canonically so that two patches with
            the same members are equal and deduplication is exact.
        centroid: mean of the member residue centroids, in angstroms.
        area: summed absolute SASA of the members, A^2, in the context the
            profile was measured in.
        mean_relative_sasa: mean of the members' relative SASA. Can exceed 1.0
            for the same reason :class:`BurialProfile` documents — the reference
            maximum is the most exposed instance in the structure, and a residue
            on a cut face can beat it.
    """

    residues: tuple[ResidueKey, ...]
    centroid: tuple[float, float, float]
    area: float
    mean_relative_sasa: float

    @property
    def size(self) -> int:
        return len(self.residues)


_Coords = tuple[float, float, float]
_Source = Target | gemmi.Structure


def _model(source: _Source) -> gemmi.Model:
    """Model 1 of a loaded target or of a bare structure.

    Both are accepted because the structure a patch is enumerated on is often
    not the deposited one: the burial check measures on an expanded, trimmed
    assembly, and that is a plain :class:`gemmi.Structure` with no
    :class:`Target` wrapper. Requiring a Target would force callers to
    re-wrap it, or worse, to enumerate on the asymmetric unit instead.
    """
    structure = source.st if isinstance(source, Target) else source
    return structure[0]


def _heavy_atoms(res: gemmi.Residue) -> list[gemmi.Atom]:
    """Non-hydrogen atoms.

    Hydrogen presence depends on experimental method and depositor, so a
    centroid or a distance that moved with it would not be comparable between
    two entries.
    """
    return [a for a in res if a.element.atomic_number > 1]


def _neighbour_search(model: gemmi.Model, cutoff: float) -> gemmi.NeighborSearch:
    """A neighbour search that cannot return crystal symmetry mates.

    The empty :class:`gemmi.UnitCell` is load-bearing. Given the deposited cell
    and spacegroup, ``find_atoms`` returns marks with non-zero ``image_idx`` —
    lattice copies — and growing a patch into one would describe a surface that
    only exists in the crystal. ``test_patch.py``'s symmetry test carries a
    control half showing the real cell does return images, so this is not a
    hypothetical.

    Deliberately a second, independent copy of the guard
    :mod:`hotspot_preflight.checks.sasa` applies to its own searches. This
    module sits below ``checks/`` in the dependency order — it imports nothing
    from there at runtime — and reaching into a check for a private helper to
    save three lines would invert that for no benefit.
    """
    return gemmi.NeighborSearch(model, gemmi.UnitCell(), cutoff).populate()


def _residue_index(model: gemmi.Model) -> dict[ResidueKey, gemmi.Residue]:
    """Key -> residue, built once per call rather than searched per lookup.

    Linear scans per residue are what turns patch enumeration from O(n*k) into
    O(n^2); on a 400-residue chain with ~200 seeds that is the difference
    between a second and a few minutes.
    """
    out: dict[ResidueKey, gemmi.Residue] = {}
    for chain in model:
        for res in chain:
            if not _heavy_atoms(res):
                continue
            out.setdefault(
                ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode)), res
            )
    return out


def _centroid_of(res: gemmi.Residue) -> _Coords:
    atoms = _heavy_atoms(res)
    n = len(atoms)
    return (
        sum(a.pos.x for a in atoms) / n,
        sum(a.pos.y for a in atoms) / n,
        sum(a.pos.z for a in atoms) / n,
    )


def _distance(a: _Coords, b: _Coords) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


def surface_residues(source: _Source, profile: "BurialProfile") -> list[ResidueKey]:
    """Residues the profile reports as at or above :data:`EXPOSED_RELATIVE_SASA`.

    Read from the profile rather than recomputed, so that "exposed" here means
    exactly what it meant in the context the caller measured — assembly, chain
    or crop. Measuring again with a different reference table would let the two
    answers disagree.

    Residues present in the profile but absent from these coordinates are
    dropped: a patch member with no atoms has no centroid and cannot be grown
    from or measured against.
    """
    present = _residue_index(_model(source))
    return sorted(
        key
        for key, value in profile.relative_sasa.items()
        if value >= EXPOSED_RELATIVE_SASA and key in present
    )


def residue_centroid(source: _Source, key: ResidueKey) -> _Coords:
    """Mean position of a residue's heavy atoms.

    A centroid rather than the CA, because patches are judged on the surface the
    side chains present: an arginine's CA can sit 6 A behind the face its
    guanidinium contributes, which is enough to move a diameter across a
    threshold.

    Raises:
        KeyError: if the residue is absent from these coordinates or has no
            heavy atoms. Returning a sentinel position would put a patch
            centroid at the origin and silently distort every distance.
    """
    res = _residue_index(_model(source)).get(key)
    if res is None:
        raise KeyError(f"{key} has no heavy atoms in these coordinates")
    return _centroid_of(res)


def neighbour_graph(
    source: _Source,
    keys: Iterable[ResidueKey],
    cutoff_a: float = NEIGHBOUR_CUTOFF_A,
) -> dict[ResidueKey, set[ResidueKey]]:
    """Adjacency among ``keys``: an edge when any heavy atoms are within cutoff.

    Every requested key appears, mapping to the empty set when isolated, so a
    caller can distinguish "no neighbours" from "not considered". Keys with no
    coordinates are included as isolated for the same reason — they are a fact
    about the input, not something to drop quietly.

    Edges cross chains when the keys do. That is correct: a site straddling a
    real interface is contiguous even though it spans two chains, and the
    patch check warns about that rather than mistaking it for two sites.
    """
    model = _model(source)
    index = _residue_index(model)
    wanted = list(dict.fromkeys(keys))
    graph: dict[ResidueKey, set[ResidueKey]] = {k: set() for k in wanted}

    wanted_set = set(wanted)
    search = _neighbour_search(model, cutoff_a)
    for key in wanted:
        res = index.get(key)
        if res is None:
            continue
        for atom in _heavy_atoms(res):
            for mark in search.find_atoms(atom.pos, "\0", radius=cutoff_a):
                cra = mark.to_cra(model)
                other = ResidueKey(
                    cra.chain.name,
                    cra.residue.seqid.num,
                    _icode(cra.residue.seqid.icode),
                )
                if other != key and other in wanted_set:
                    graph[key].add(other)
                    graph[other].add(key)
    return graph


def connected_components(
    graph: dict[ResidueKey, set[ResidueKey]],
) -> list[list[ResidueKey]]:
    """Connected components of a neighbour graph, each sorted, outer list sorted.

    Shared by :func:`patch_contiguous` and the patch check so the two cannot
    give different answers about the same set of residues.
    """
    seen: set[ResidueKey] = set()
    components: list[list[ResidueKey]] = []
    for start in sorted(graph):
        if start in seen:
            continue
        component: list[ResidueKey] = []
        queue = deque([start])
        seen.add(start)
        while queue:
            node = queue.popleft()
            component.append(node)
            for other in sorted(graph.get(node, ())):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        components.append(sorted(component))
    return sorted(components)


# ---------------------------------------------------------------------------
# Patches
# ---------------------------------------------------------------------------


def _grow(
    seed: ResidueKey,
    graph: dict[ResidueKey, set[ResidueKey]],
    centroids: dict[ResidueKey, _Coords],
) -> tuple[ResidueKey, ...]:
    """Grow one patch outward from ``seed``, nearest exposed neighbour first.

    Growth follows graph edges, so the result is contiguous by construction, and
    is gated on distance from the *seed* centroid rather than from the patch's
    moving centroid. A moving centroid lets a patch creep arbitrarily far by
    small steps, which is how a "patch" ends up wrapping half a domain; a fixed
    seed bounds the span at ``2 * PATCH_RADIUS_A`` unconditionally.

    Nearest-first with the residue key as tie-break makes the result independent
    of set and dict iteration order, which is what keeps enumeration
    reproducible between runs and between interpreters.
    """
    origin = centroids[seed]
    members = [seed]
    chosen = {seed}
    candidates = {
        k
        for k in graph[seed]
        if _distance(origin, centroids[k]) <= PATCH_RADIUS_A
    }

    while candidates and len(members) < PATCH_MAX_RESIDUES:
        best = min(candidates, key=lambda k: (_distance(origin, centroids[k]), k))
        candidates.discard(best)
        members.append(best)
        chosen.add(best)
        for other in graph[best]:
            if other in chosen or other in candidates:
                continue
            if _distance(origin, centroids[other]) <= PATCH_RADIUS_A:
                candidates.add(other)

    return tuple(sorted(members))


def enumerate_patches(
    source: _Source,
    profile: "BurialProfile",
    *,
    chain: str | None = None,
    max_patches: int | None = None,
) -> list[Patch]:
    """Every candidate surface patch, one grown per exposed seed residue.

    Patches overlap heavily and that is intended — a binder's footprint is not
    partitioned, so a seed-per-residue sweep is what avoids missing a site that
    happens to straddle two arbitrary partitions. Identical residue sets are
    collapsed, which is where most of the redundancy goes.

    Returned widest-exposure first (descending area, then residue identity), so
    that ``max_patches`` keeps the most promising candidates rather than an
    arbitrary prefix. The order is total, hence reproducible.

    Args:
        source: loaded target, or a structure such as a trimmed assembly.
        profile: exposure already measured on the context being enumerated.
        chain: restrict seeds and members to one author chain. Leave as ``None``
            to allow interface-spanning patches.
        max_patches: keep only this many. ``None`` keeps all.

    Raises:
        ValueError: if ``max_patches`` is not positive. Zero would silently
            return nothing, which reads as "no patches found".
    """
    if max_patches is not None and max_patches < 1:
        raise ValueError(f"max_patches must be at least 1, got {max_patches}")

    exposed = surface_residues(source, profile)
    if chain is not None:
        exposed = [k for k in exposed if k.auth_asym_id == chain]
    if len(exposed) < PATCH_MIN_RESIDUES:
        return []

    model = _model(source)
    index = _residue_index(model)
    centroids = {k: _centroid_of(index[k]) for k in exposed}
    graph = neighbour_graph(source, exposed)

    by_members: dict[tuple[ResidueKey, ...], Patch] = {}
    for seed in exposed:
        members = _grow(seed, graph, centroids)
        if len(members) < PATCH_MIN_RESIDUES or members in by_members:
            continue
        by_members[members] = _build_patch(members, centroids, profile)

    patches = sorted(by_members.values(), key=lambda p: (-p.area, p.residues))
    return patches if max_patches is None else patches[:max_patches]


def _build_patch(
    members: Sequence[ResidueKey],
    centroids: dict[ResidueKey, _Coords],
    profile: "BurialProfile",
) -> Patch:
    n = len(members)
    points = [centroids[k] for k in members]
    return Patch(
        residues=tuple(members),
        centroid=(
            sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n,
        ),
        area=sum(profile.absolute_sasa.get(k, 0.0) for k in members),
        mean_relative_sasa=sum(profile.relative_sasa[k] for k in members) / n,
    )


def patch_diameter(source: _Source, patch: Patch) -> float:
    """Widest separation between any two member centroids, in angstroms.

    The widest separation and not twice a radius of gyration, because what
    matters is whether a binder can span the whole set: one outlier residue
    makes a site undesignable even when the rest is compact, and a radius of
    gyration averages exactly that away.
    """
    index = _residue_index(_model(source))
    missing = [k for k in patch.residues if k not in index]
    if missing:
        raise KeyError(
            f"{', '.join(str(k) for k in missing)} have no heavy atoms in these "
            f"coordinates, so the patch has no measurable diameter"
        )
    centroids = [_centroid_of(index[k]) for k in patch.residues]
    return max(
        (
            _distance(centroids[i], centroids[j])
            for i in range(len(centroids))
            for j in range(i + 1, len(centroids))
        ),
        default=0.0,
    )


def patch_contiguous(
    source: _Source, patch: Patch, cutoff_a: float = NEIGHBOUR_CUTOFF_A
) -> bool:
    """True when the members form a single connected neighbour-graph component.

    A patch with two components is two sites. A binder contacts one, so the
    design is aimed at a hotspot set it can never satisfy — and the design tool
    will report healthy scores for the half it did reach.
    """
    graph = neighbour_graph(source, patch.residues, cutoff_a=cutoff_a)
    return len(connected_components(graph)) <= 1
