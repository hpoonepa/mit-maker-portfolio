# SPDX-License-Identifier: MIT
"""Solvent accessibility: the measurement, with no opinion about it.

Split from :mod:`.burial` so that the number and the verdict live apart. This
module answers "how exposed is this residue, in this set of coordinates, under
exactly these parameters"; it never decides whether that is acceptable. Every
threshold is in :mod:`.burial`.

The structure-geometry helpers (chain subsetting, neighbour search, assembly
trimming) are here rather than next to the check because
:func:`compute_burial` needs them: burial is a local property, so measuring it
on a 180-chain capsid means trimming first, and that makes trimming part of the
measurement rather than part of the judgement.

Two facts drive the parameter choices, both verified rather than assumed:

* **Cross-program SASA values are not comparable.** freesasa uses ProtOr
  united-atom radii, DSSP-derived tables use element radii, and the systematic
  gap is a few percent. So one library computes everything here, numerator and
  denominator alike, and every pinned parameter is recorded on the result.
* **freesasa does not raise on an unknown atom.** ``Classifier.radius``
  returns -1.0, which silently becomes a negative-radius sphere.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable, Iterable, Mapping, Sequence

import freesasa
import gemmi

from ..residue import ResidueKey
from ..structure import _icode

__all__ = [
    "SASA_PROBE_RADIUS", "SASA_ALGORITHM", "SASA_N_SLICES", "SASA_CLASSIFIER",
    "REFERENCE_METHOD", "NEIGHBOUR_CUTOFF_A", "PUBLISHED_MAX_SASA",
    "REFERENCE_SUBSTITUTE_MAX", "REQUIRED_PARAMETER_KEYS", "VALID_CONTEXTS",
    "BurialProfile", "reference_max_sasa", "reference_digest",
    "trim_to_neighbourhood", "compute_burial",
]

SASA_PROBE_RADIUS = 1.4
"""Water probe radius, angstroms. freesasa's default, pinned not inherited."""

NEIGHBOUR_CUTOFF_A = 12.0
"""Chains with no atom this close to the focus chain are dropped before SASA.

Burial is local — a 1.4 A probe cannot be occluded from much further than a
couple of atomic diameters — so this is correct as well as necessary: 6F5J's
single assembly generator carries 60 operators and expands 3 chains into 180
chains and 420k atoms, which is not a tractable SASA calculation.
"""

SASA_ALGORITHM = "LeeRichards"
SASA_N_SLICES = 20
SASA_CLASSIFIER = "freesasa-default (ProtOr united-atom radii, Tsai 1999)"
REFERENCE_METHOD = "max-tripeptide-sasa-in-structure, published fallback"
VALID_CONTEXTS = ("assembly", "chain", "crop")

# Tien et al. 2013, PLoS ONE 8(11):e80635, Table 1, "Theoretical" column: the
# SASA of residue X in an extended Gly-X-Gly tripeptide. A fallback only; see
# reference_max_sasa for why the empirical route is preferred.
PUBLISHED_MAX_SASA: dict[str, float] = {
    "ALA": 129.0, "ARG": 274.0, "ASN": 195.0, "ASP": 193.0, "CYS": 167.0,
    "GLN": 225.0, "GLU": 223.0, "GLY": 104.0, "HIS": 224.0, "ILE": 197.0,
    "LEU": 201.0, "LYS": 236.0, "MET": 224.0, "PHE": 240.0, "PRO": 159.0,
    "SER": 155.0, "THR": 172.0, "TRP": 285.0, "TYR": 263.0, "VAL": 174.0,
}

REFERENCE_SUBSTITUTE_MAX = max(PUBLISHED_MAX_SASA.values())
"""Denominator for a residue type no route can price, e.g. an exotic modified
residue. Deliberately the largest standard maximum: it understates exposure,
and understating how exposed we claim a site is fails safe."""

# Coarse element radii for atoms the classifier prices at -1.0. Only
# non-standard residues reach this, and every use is counted in
# BurialProfile.parameters so a reader can see that it happened.
FALLBACK_ELEMENT_RADII = {"C": 1.80, "N": 1.64, "O": 1.46, "S": 1.77, "P": 1.90}
FALLBACK_ATOM_RADIUS = 1.80

REQUIRED_PARAMETER_KEYS = frozenset({
    "probe_radius", "algorithm", "algorithm_parameter", "n_slices",
    "classifier", "include_hydrogens", "include_hetatm", "include_solvent",
    "relative_sasa_method", "reference_published_source",
    "n_reference_empirical", "n_reference_published",
    "n_reference_substituted", "n_fallback_radius_atoms",
    "neighbour_cutoff_a", "focus_chain", "freesasa_version", "gemmi_version",
    "reference_id",
})
"""What :attr:`BurialProfile.parameters` must carry for the numbers to be
reproducible without reading this file."""

# freesasa warns to stderr once per unknown atom. We count those into
# `parameters` instead; a check returns Findings and must not print.
freesasa.setVerbosity(freesasa.silent)

_CLASSIFIER = freesasa.Classifier()

_ResidueItem = tuple[str, gemmi.Residue]


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - installed in all envs
        return "unknown"


@dataclass(frozen=True)
class BurialProfile:
    """Per-residue solvent accessibility in one structural context.

    ``relative_sasa`` can exceed 1.0, and that is not a bug: the reference
    maximum is the most exposed instance of that residue type in the structure,
    and a residue on a freshly cut crop face can beat anything in the intact
    protein. Clamping would hide exactly the signal we are looking for.

    ``reference_id`` identifies the denominator scale this profile was measured
    against; two profiles are only subtractable if theirs match, which
    ``burial.compare_contexts`` enforces. It defaults to empty so that adding
    it did not break positional construction, but :func:`compute_burial`
    always fills it in and no caller should supply it.
    """

    relative_sasa: dict[ResidueKey, float]
    absolute_sasa: dict[ResidueKey, float]
    context: str
    n_chains: int
    parameters: dict[str, Any]
    reference_id: str = ""


# ---------------------------------------------------------------------------
# Atom selection and SASA
# ---------------------------------------------------------------------------


def _is_amino_acid(res: gemmi.Residue) -> bool:
    """True for polymer amino acids, modified ones such as MSE included.

    Read from gemmi's residue table rather than from entity setup, so this
    works on structures we build ourselves — crops, trimmed assemblies —
    without having to re-run ``setup_entities`` on each one.
    """
    info = gemmi.find_tabulated_residue(res.name)
    return info is not None and info.is_amino_acid()


def _heavy_atoms(res: gemmi.Residue) -> list[gemmi.Atom]:
    """Non-hydrogen atoms. Hydrogen presence depends on method and depositor,
    and a SASA that moves with that is not comparable between the three
    contexts the burial check subtracts from one another."""
    return [a for a in res if a.element.atomic_number > 1]


def _atom_radius(resname: str, atom: gemmi.Atom) -> tuple[float, bool]:
    """Return ``(radius, used_fallback)``.

    ``Classifier.radius`` returns -1.0 rather than raising for a pair it does
    not know, so the negative must be tested for explicitly or it silently
    becomes a negative-radius sphere.
    """
    radius = _CLASSIFIER.radius(resname, atom.name)
    if radius > 0:
        return radius, False
    element = atom.element.name.upper()
    return FALLBACK_ELEMENT_RADII.get(element, FALLBACK_ATOM_RADIUS), True


def _sasa_by_residue(
    items: Sequence[_ResidueItem],
) -> tuple[dict[ResidueKey, float], int]:
    """Absolute SASA per residue, via ``calcCoord``.

    Coordinates go in as a flat array rather than through a temporary PDB file:
    PDB format cannot express more than 62 chains or 5-digit residue numbers,
    and an expanded assembly routinely exceeds both, so a round-trip would
    silently mangle the very identities this package exists to protect.
    """
    coords: list[float] = []
    radii: list[float] = []
    spans: list[tuple[ResidueKey, int, int]] = []
    n_fallback = 0

    for chain_name, res in items:
        start = len(radii)
        for atom in _heavy_atoms(res):
            radius, fell_back = _atom_radius(res.name, atom)
            n_fallback += fell_back
            coords.extend((atom.pos.x, atom.pos.y, atom.pos.z))
            radii.append(radius)
        if len(radii) > start:
            key = ResidueKey(chain_name, res.seqid.num, _icode(res.seqid.icode))
            spans.append((key, start, len(radii)))

    if not radii:
        return {}, 0

    params = freesasa.Parameters({
        "algorithm": SASA_ALGORITHM,
        "probe-radius": SASA_PROBE_RADIUS,
        "n-slices": SASA_N_SLICES,
    })
    result = freesasa.calcCoord(coords, radii, params)
    areas = {
        key: sum(result.atomArea(i) for i in range(start, end))
        for key, start, end in spans
    }
    return areas, n_fallback


def _polymer_items(structure: gemmi.Structure) -> list[_ResidueItem]:
    return [
        (chain.name, res)
        for chain in structure[0]
        for res in chain
        if _is_amino_acid(res) and _heavy_atoms(res)
    ]


# ---------------------------------------------------------------------------
# The relative-SASA reference
# ---------------------------------------------------------------------------


def reference_max_sasa(
    structure: gemmi.Structure,
) -> tuple[dict[str, float], dict[str, str]]:
    """Per-residue-type reference maxima, computed from the structure itself.

    Method (``REFERENCE_METHOD``): for every residue with both covalent
    neighbours present and sequence-contiguous, compute its SASA in the context
    of just that tripeptide; take the maximum over all instances of each type.
    Returns ``(maxima, provenance)``, provenance marking each type
    ``"empirical"`` or ``"published"``.

    Not published maxima, because cross-program SASA values are not comparable
    — freesasa uses ProtOr united-atom radii, DSSP-derived tables use element
    radii — and dividing a freesasa numerator by a foreign denominator puts
    that systematic gap straight into a threshold comparison. Using the same
    probe, algorithm, radii and classifier for both removes it.

    A tripeptide and not an isolated residue, because an isolated residue's
    backbone N and C are fully exposed as no residue in a chain ever is; that
    inflates the denominator by ~40 A^2 and would roughly halve every ratio.
    The tripeptide caps the backbone, which is what the Gly-X-Gly convention is
    for. Chain termini are skipped for the same reason — a free terminus has no
    cap. Cross-validated against Tien et al.'s theoretical maxima in
    ``test_empirical_reference_agrees_with_published_maxima``: all 20 standard
    types land within 25%.

    Types the structure cannot calibrate fall back to
    :data:`PUBLISHED_MAX_SASA`, and the substitution is recorded, not hidden.
    """
    maxima: dict[str, float] = {}
    for chain in structure[0]:
        residues = [r for r in chain if _is_amino_acid(r) and _heavy_atoms(r)]
        for i in range(1, len(residues) - 1):
            prev, this, nxt = residues[i - 1], residues[i], residues[i + 1]
            if (
                this.seqid.num - prev.seqid.num != 1
                or nxt.seqid.num - this.seqid.num != 1
            ):
                continue
            areas, _ = _sasa_by_residue(
                [(chain.name, prev), (chain.name, this), (chain.name, nxt)]
            )
            key = ResidueKey(chain.name, this.seqid.num, _icode(this.seqid.icode))
            area = areas.get(key)
            if area is not None:
                maxima[this.name] = max(maxima.get(this.name, 0.0), area)

    provenance = {name: "empirical" for name in maxima}
    for name, published in PUBLISHED_MAX_SASA.items():
        if name not in maxima:
            maxima[name] = published
            provenance[name] = "published"
    return maxima, provenance


def reference_digest(
    maxima: Mapping[str, float], provenance: Mapping[str, str]
) -> str:
    """A short stable identifier for one denominator scale.

    SHA-256 over the sorted table and its provenance, truncated. Deliberately
    not :func:`hash`, which is salted per process and would differ between two
    runs of the same pipeline, making a stored ``reference_id`` useless for
    deciding whether two run records are comparable. Provenance is part of the
    identity: a type priced empirically and one that happened to land on the
    same published value are the same number reached two ways.
    """
    payload = ";".join(
        f"{name}={maxima[name]:.6f}:{provenance.get(name, '?')}"
        for name in sorted(maxima)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _relative(
    area: float, resname: str, maxima: Mapping[str, float]
) -> tuple[float, bool]:
    reference = maxima.get(resname)
    if reference is None or reference <= 0:
        return area / REFERENCE_SUBSTITUTE_MAX, True
    return area / reference, False


# ---------------------------------------------------------------------------
# Structure geometry
# ---------------------------------------------------------------------------


def _chain_names(structure: gemmi.Structure) -> list[str]:
    return [c.name for c in structure[0]]


def _subset_structure(
    source: gemmi.Structure,
    chains: Iterable[str],
    keep: Callable[[gemmi.Residue], bool] | None = None,
) -> gemmi.Structure:
    """A new single-model structure holding the named chains' kept residues.

    Deliberately leaves the unit cell unset: nothing downstream may apply
    crystal symmetry to these, and an absent cell makes that structural rather
    than a matter of remembering to pass a flag.
    """
    out = gemmi.Structure()
    out.name = source.name
    out.spacegroup_hm = "P 1"
    model = gemmi.Model("1")
    wanted = set(chains)
    for chain in source[0]:
        if chain.name not in wanted:
            continue
        new = gemmi.Chain(chain.name)
        for res in chain:
            if keep is None or keep(res):
                new.add_residue(res)
        if len(new):
            model.add_chain(new)
    out.add_model(model)
    return out


def _neighbour_search(model: gemmi.Model, cutoff: float) -> gemmi.NeighborSearch:
    """A neighbour search that cannot return crystal symmetry mates.

    The empty :class:`gemmi.UnitCell` is the whole point. Given a real cell and
    spacegroup, ``find_atoms`` returns marks with non-zero ``image_idx`` —
    lattice neighbours — and counting those as partners would report a crystal
    contact as biological burial. Verified on 1TIM (P 2 1 2 1 2 1): the real
    cell yields images 1-3, an empty cell only image 0.
    """
    # Do not "simplify" the empty UnitCell away: test_burial.py::
    # test_neighbour_search_ignores_crystal_symmetry fails if you pass the real
    # cell, and it carries a control half proving the hazard is not theoretical.
    return gemmi.NeighborSearch(model, gemmi.UnitCell(), cutoff).populate()


def trim_to_neighbourhood(
    structure: gemmi.Structure,
    focus_chain: str | Sequence[str],
    cutoff: float = NEIGHBOUR_CUTOFF_A,
) -> gemmi.Structure:
    """Keep the focus chains plus every chain with an atom within ``cutoff``.

    Accepts one name or several. Several matters for a multi-chain antigen: the
    trim's justification is that a chain beyond the cutoff cannot occlude
    anything on the focus chain, which is true and assumes a single focus. Trim
    a two-chain antigen to its first chain and the second is discarded whenever
    the two are far apart, taking any site on it with it. Measured on 6hhd and
    12ut, where a declared antigen chain vanished and the residues on it were
    then reported as killed rather than as missing.

    Idempotent, so trimming an already-trimmed structure is a cheap no-op
    rather than a different answer.

    Raises:
        ValueError: if no focus chain is given, or if any named chain is absent.
            Absent is an error rather than a skip because the caller named it to
            protect it; ignoring the name returns a structure missing the very
            chain the call was made to keep.
    """
    focus = [focus_chain] if isinstance(focus_chain, str) else list(focus_chain)
    if not focus:
        raise ValueError("trim_to_neighbourhood needs at least one focus chain")
    names = _chain_names(structure)
    missing = [c for c in focus if c not in names]
    if missing:
        raise ValueError(
            f"chain {(missing[0] if len(missing) == 1 else missing)!r} is not in "
            f"this structure; chains are {names}"
        )
    if len(names) == 1:
        return structure

    model = structure[0]
    search = _neighbour_search(model, cutoff)
    keep = set(focus)
    for name in focus:
        for res in model[name]:
            if not _is_amino_acid(res):
                continue
            for atom in _heavy_atoms(res):
                for mark in search.find_atoms(atom.pos, "\0", radius=cutoff):
                    keep.add(model[mark.chain_idx].name)
    return _subset_structure(structure, keep)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def compute_burial(
    structure: gemmi.Structure,
    context: str,
    focus_chain: str | None = None,
    *,
    reference: tuple[Mapping[str, float], Mapping[str, str]] | None = None,
) -> BurialProfile:
    """Relative and absolute SASA for one structural context.

    Args:
        structure: coordinates already in the context you want measured.
        context: one of ``"assembly"``, ``"chain"``, ``"crop"``; recorded on the
            profile so a finding can state which contexts it compared.
        focus_chain: restrict the profile to this chain, trimming a large
            assembly to its neighbourhood first. ``None`` profiles every chain.
        reference: a table from :func:`reference_max_sasa`. Pass the *same*
            table to every context you intend to subtract — a table recomputed
            per context rescales the denominators, and the difference between
            two ratios then means nothing. A crop of twenty residues can
            calibrate almost no residue types, so this matters in practice.
            ``None`` derives one from ``structure``, correct only standalone.

    Raises:
        ValueError: on an unknown context or an unknown focus chain.
    """
    if context not in VALID_CONTEXTS:
        raise ValueError(f"context must be one of {VALID_CONTEXTS}, got {context!r}")
    if focus_chain is not None and focus_chain not in _chain_names(structure):
        raise ValueError(
            f"chain {focus_chain!r} is not in this structure; "
            f"chains are {_chain_names(structure)}"
        )

    work = structure
    if focus_chain is not None and len(structure[0]) > 1:
        work = trim_to_neighbourhood(structure, focus_chain)

    maxima, provenance = (
        reference if reference is not None else reference_max_sasa(work)
    )

    items = _polymer_items(work)
    absolute, n_fallback = _sasa_by_residue(items)
    names = {
        ResidueKey(chain, res.seqid.num, _icode(res.seqid.icode)): res.name
        for chain, res in items
    }

    relative: dict[ResidueKey, float] = {}
    n_substituted = 0
    for key, area in absolute.items():
        if focus_chain is not None and key.auth_asym_id != focus_chain:
            continue
        ratio, substituted = _relative(area, names[key], maxima)
        n_substituted += substituted
        relative[key] = ratio

    if focus_chain is not None:
        absolute = {
            k: v for k, v in absolute.items() if k.auth_asym_id == focus_chain
        }

    counts = Counter(provenance.values())
    digest = reference_digest(maxima, provenance)
    parameters: dict[str, Any] = {
        "probe_radius": SASA_PROBE_RADIUS,
        "algorithm": SASA_ALGORITHM,
        "algorithm_parameter": "n_slices",
        "n_slices": SASA_N_SLICES,
        "classifier": SASA_CLASSIFIER,
        "include_hydrogens": False,
        "include_hetatm": False,
        "include_solvent": False,
        "relative_sasa_method": REFERENCE_METHOD,
        "reference_published_source": "Tien et al. 2013 PLoS ONE 8(11):e80635",
        "n_reference_empirical": counts.get("empirical", 0),
        "n_reference_published": counts.get("published", 0),
        "n_reference_substituted": n_substituted,
        "n_fallback_radius_atoms": n_fallback,
        "neighbour_cutoff_a": NEIGHBOUR_CUTOFF_A,
        "focus_chain": focus_chain,
        "freesasa_version": _package_version("freesasa"),
        "gemmi_version": gemmi.__version__,
        "reference_id": digest,
    }
    return BurialProfile(
        relative_sasa=relative,
        absolute_sasa=absolute,
        context=context,
        n_chains=len(work[0]),
        parameters=parameters,
        reference_id=digest,
    )
