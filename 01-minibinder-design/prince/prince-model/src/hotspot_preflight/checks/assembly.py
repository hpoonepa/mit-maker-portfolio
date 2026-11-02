# SPDX-License-Identifier: MIT
"""Building the biological assembly from the deposited asymmetric unit.

The two are routinely different, and the difference is the point. A crystal or
cryo-EM entry deposits whatever the experiment resolved; the biological form is
described separately, as a list of operators to apply to it. 6F5J's single
assembly generator carries 60 operators and turns 3 chains into 180 — so a
residue that looks solvent-exposed in the deposited file can be completely
packed in the real particle.

This module does that expansion and nothing else. It holds no thresholds and
makes no judgement; it imports from :mod:`.sasa` for atom selection only, and
nothing here imports from :mod:`.burial`, which is what keeps the three modules
acyclic.

The one subtlety is chain naming. gemmi's expansion has to invent names for the
copies, and every mode it offers loses information in some way. Keeping the
author numbering addressable through the expansion is handled by
:func:`_restore_author_chain_names`, which verifies rather than assumes.
"""

from __future__ import annotations

import gemmi

from ..structure import Target
from .sasa import _chain_names, _heavy_atoms

__all__ = ["expand_assembly"]

IDENTITY_TOLERANCE_A = 1e-4
"""How close two atoms must be to be called the same atom.

Used to identify the untransformed copy among the expanded ones. The identity
operator reproduces coordinates exactly, so this only has to absorb float
round-trip noise, not real displacement.
"""


def _first_heavy_position(chain: gemmi.Chain) -> gemmi.Position | None:
    for res in chain:
        for atom in _heavy_atoms(res):
            return atom.pos
    return None


def _restore_author_chain_names(
    original: gemmi.Structure, expanded: gemmi.Structure
) -> None:
    """Rename each untransformed copy back to its author chain id.

    ``AddNumber`` renames chain A to A1, A2, ..., so a
    :class:`~hotspot_preflight.residue.ResidueKey` built from the asymmetric
    unit would no longer index into the assembly. Renaming the identity copy
    back fixes that once for every caller.

    Which copy is the identity one is *verified* by coordinates rather than
    assumed from the ordering, and an ambiguous or missing match raises. The
    ordering happens to put the identity copy first today, but that is a
    gemmi implementation detail; silently trusting it would mis-map every
    residue key the moment it changed.
    """
    taken = set(_chain_names(expanded))
    for src in original[0]:
        reference = _first_heavy_position(src)
        if reference is None:
            continue
        if src.name in taken:
            raise ValueError(
                f"assembly expansion produced a chain already named "
                f"{src.name!r}; cannot restore author chain names unambiguously"
            )
        matches = [
            chain
            for chain in expanded[0]
            if chain.name.startswith(src.name)
            and chain.name[len(src.name) :].isdigit()
            and (pos := _first_heavy_position(chain)) is not None
            and pos.dist(reference) < IDENTITY_TOLERANCE_A
        ]
        if len(matches) != 1:
            raise ValueError(
                f"cannot identify the untransformed copy of chain {src.name!r} "
                f"in the expanded assembly ({len(matches)} candidates match its "
                f"coordinates); residue keys could not be mapped safely"
            )
        matches[0].name = src.name


def expand_assembly(
    target: Target, assembly_name: str | None = None
) -> gemmi.Structure:
    """Expand the deposited biological assembly.

    ``AddNumber`` is the only safe naming mode: ``Dup`` produces duplicate
    chain names and ``Short`` silently reuses single-character names past 62
    chains, either of which corrupts the per-chain SASA bookkeeping that the
    burial check does downstream. 6F5J expands to 180 chains, so that is not a
    hypothetical limit.

    Args:
        target: the loaded structure.
        assembly_name: which declared assembly to build. Defaults to the first,
            which is the biological unit for the entries we have checked.

    Raises:
        ValueError: if the entry declares no assembly, or names an unknown one.
            A caller wanting a fallback must choose it explicitly — treating
            the asymmetric unit as the assembly is the silent-wrong answer the
            burial check exists to prevent.
    """
    names = [a.name for a in target.st.assemblies]
    if not names:
        raise ValueError(
            f"{target.entry_id} declares no biological assembly; "
            f"there is nothing to expand"
        )
    name = names[0] if assembly_name is None else assembly_name
    if name not in names:
        raise ValueError(
            f"{target.entry_id} has no assembly {name!r}; declared: {names}"
        )
    expanded = target.st.clone()
    expanded.transform_to_assembly(name, gemmi.HowToNameCopiedChain.AddNumber)
    _restore_author_chain_names(target.st, expanded)
    return expanded
