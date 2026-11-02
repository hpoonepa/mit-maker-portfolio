"""Locating benchmark coordinates, and isolating the antigen from the complex.

Shared by the `preflight` filter and the `geometric` predictor so there is one
structure locator and one definition of "the antigen", not two that can drift.

The important function here is :func:`antigen_only`, and it is not a
convenience. **Every benchmark entry is an antibody-antigen complex**, so the
antigen's solvent accessibility measured on the deposited file is accessibility
*with the antibody still bound* — which buries the very epitope we are trying
to find. Left uncorrected that is circular in the worst direction: the true
epitope looks occluded, a burial check kills it, and an exposure-driven
predictor ranks it last. The false-rejection rate would be enormous and the
AUROC near zero, both for reasons that have nothing to do with the method.

Spec section 4.1 says the filter metrics are measured "on the antigen alone",
and this is where that happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import gemmi

from hotspot_preflight.checks.assembly import expand_assembly
from hotspot_preflight.checks.sasa import trim_to_neighbourhood
from hotspot_preflight.structure import Target, load_target

__all__ = [
    "StructureUnavailable",
    "STRUCTURE_SUFFIXES",
    "locate_structure",
    "antigen_only",
    "antigen_assembly",
    "load_antigen",
    "StructureLocator",
]

LOGGER = logging.getLogger(__name__)

#: Tried in order against ``<dir>/<pdb_id><suffix>``, lowercase id then
#: uppercase. The two RCSB routes disagree on case — the coordinate download
#: wants uppercase and the PDBe updated-mmCIF route wants lowercase — so a
#: cache populated by either must resolve. ``.cif.gz`` is first because that is
#: what the benchmark download actually writes.
STRUCTURE_SUFFIXES: tuple[str, ...] = (
    ".cif.gz", "_updated.cif", ".cif", ".mmcif", ".pdb", ".pdb.gz",
)


class StructureUnavailable(FileNotFoundError):
    """No readable structure for this instance.

    Loud rather than swallowed: a missing structure silently treated as
    "nothing was killed" would pull the false-rejection rate towards zero,
    which is the one direction that flatters us. Callers drop such instances
    before evaluating and log the drop.
    """


def locate_structure(structure_dir: Path, pdb_id: str) -> Path | None:
    """First existing candidate path for ``pdb_id``, or None."""
    for spelling in (pdb_id.lower(), pdb_id.upper()):
        for suffix in STRUCTURE_SUFFIXES:
            candidate = structure_dir / f"{spelling}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def antigen_only(target: Target, antigen_chains: Iterable[str]) -> Target:
    """A copy of ``target`` holding only the named chains.

    Returns a new :class:`Target` sharing the original ``path`` and ``block``:
    the block is the entry's metadata, including the declared sequence and the
    unobserved-residue category, and those statements about the antigen chains
    remain true when the antibody chains are dropped. Sharing it keeps
    ``check_resolved`` able to tell "unmodelled" from "not declared".

    Raises:
        ValueError: if none of ``antigen_chains`` is present, which means the
            manifest and the coordinates disagree and any number computed from
            them would be meaningless.
    """
    keep = {c.strip() for c in antigen_chains if c and c.strip()}
    if not keep:
        raise ValueError("no antigen chains given")

    stripped = target.st.clone()
    present = {chain.name for model in stripped for chain in model}
    missing = keep - present
    if keep & present == set():
        raise ValueError(
            f"none of the antigen chains {sorted(keep)} are in "
            f"{target.path.name} (it has {sorted(present)})"
        )
    if missing:
        LOGGER.debug("antigen chains %s absent from %s", sorted(missing), target.path.name)

    for model in stripped:
        # Names are collected first and removed by name afterwards: mutating a
        # model while iterating it skips entries, which silently leaves
        # antibody chains in place and reintroduces the burial artifact this
        # function exists to prevent.
        drop = [chain.name for chain in model if chain.name not in keep]
        for name in drop:
            while any(chain.name == name for chain in model):
                model.remove_chain(name)

    stripped.setup_entities()
    return Target(path=target.path, st=stripped, block=target.block)


def _base_chain_name(name: str) -> str:
    """``"D2"`` -> ``"D"``. Assembly expansion appends a copy number.

    ``gemmi.HowToNameCopiedChain.AddNumber`` renames copies by suffixing a
    digit, so the copies of antigen chain ``D`` are ``D``, ``D2``, ``D3``. A
    name that is all digits, or has no digits, is returned unchanged.
    """
    stripped = name.rstrip("0123456789")
    return stripped or name


def antigen_assembly(
    target: Target,
    antigen_chains: Sequence[str],
    *,
    focus_chain: str | None = None,
) -> Target | None:
    """The biological assembly, reduced to copies of the antigen chains.

    This is what makes burial-in-assembly meaningful on an antibody complex
    **without** being circular. The declared assembly of an antibody-antigen
    entry contains the antibody, so measuring burial on it would report the
    antibody burying the epitope — which is the answer we are trying to
    predict. Keeping *only* copies of the antigen chains leaves exactly the
    occlusion we legitimately want to detect: one antigen subunit buried by
    another, which is the 6F5J capsid failure this whole tool exists for.

    Every non-antigen chain is dropped, including other Fabs in the same
    entry: a neighbouring antibody is still an antibody, and letting it
    occlude the epitope would reintroduce the circularity by the back door.

    Returns None when the entry declares no assembly or expansion fails, so
    the caller can fall back to the asymmetric unit and *count* it.
    """
    if not target.st.assemblies:
        return None
    keep = {c.strip() for c in antigen_chains if c and c.strip()}
    try:
        expanded = expand_assembly(target)
    except (RuntimeError, ValueError) as exc:
        # Expansion legitimately fails when the assembly references subchains
        # that are not in the file. Counted by the caller, never silent.
        LOGGER.debug("assembly expansion failed for %s: %s", target.path.name, exc)
        return None

    for model in expanded:
        drop = [
            chain.name
            for chain in model
            if chain.name not in keep and _base_chain_name(chain.name) not in keep
        ]
        for name in drop:
            while any(chain.name == name for chain in model):
                model.remove_chain(name)

    if not any(True for model in expanded for _ in model):
        return None

    # Trim to the focus chain's neighbourhood, exactly as ``check_burial``
    # does internally. Without this an icosahedral capsid expands to every
    # antigen copy — 9mpz reaches 36,540 residues — and the predictor's
    # per-residue concavity and connectivity features are quadratic in that
    # count, so one entry stalls the whole run for tens of minutes. Trimming
    # is not a coverage cap: occlusion by a partner requires proximity, so a
    # copy beyond the neighbourhood cutoff cannot bury anything on the focus
    # chain, and dropping it changes no burial verdict.
    # EVERY declared antigen chain is a focus, not just the first. Trimming to
    # one discards a second antigen chain whenever the two are far apart, and
    # the epitope residues on it are then absent from the structure the filter
    # judges — which the benchmark scores as the filter killing them. Measured
    # on 6hhd (chain C) and 12ut (chain w): 262 epitope residues across 32
    # instances reported as NO_SUCH_CHAIN kills that were really a dropped chain.
    # Focus is EVERY declared antigen chain unless the caller names one. An
    # explicit single focus_chain stays honoured, because a caller that names
    # one is asking about that chain; the default must not be the first chain by
    # accident of ordering.
    focus = (
        [focus_chain] if focus_chain
        else [c.strip() for c in antigen_chains if c and c.strip()]
    )
    names = {chain.name for model in expanded for chain in model}
    present = [c for c in dict.fromkeys(focus) if c in names]
    if present:
        try:
            expanded = trim_to_neighbourhood(expanded, present)
        except (RuntimeError, ValueError) as exc:
            LOGGER.debug("trim failed for %s: %s", target.path.name, exc)

    expanded.setup_entities()
    # The reduced structure is no longer the declared assembly, so its
    # assembly list is cleared rather than left pointing at chains that are
    # gone — which is what makes expand_assembly raise "no subchain".
    expanded.assemblies.clear()
    return Target(path=target.path, st=expanded, block=target.block)


def load_antigen(
    structure_dir: Path,
    pdb_id: str,
    antigen_chains: Sequence[str],
    *,
    use_assembly: bool = True,
) -> tuple[Target, bool]:
    """Locate, load and reduce to the antigen in one call.

    Returns ``(target, used_assembly)``. ``used_assembly`` is False when the
    asymmetric unit was used because no assembly was declared or expansion
    failed — the caller is expected to count those, because on such an entry
    every assembly delta is zero by construction and assembly-awareness is not
    being exercised at all.

    Raises:
        StructureUnavailable: when no coordinates exist for ``pdb_id``.
        ValueError: when the antigen chains are not in the file.
    """
    path = locate_structure(structure_dir, pdb_id)
    if path is None:
        raise StructureUnavailable(
            f"no structure for {pdb_id} in {structure_dir} (tried "
            f"{list(STRUCTURE_SUFFIXES)}, both cases). Drop this instance "
            f"before evaluating; treating it as 'nothing killed' would bias "
            f"the false-rejection rate towards zero."
        )
    target = load_target(path)
    if use_assembly:
        # No focus_chain: antigen_assembly then trims to the neighbourhood of
        # EVERY declared antigen chain. Passing the first one here is what
        # silently discarded the second chain of a two-chain antigen, and with
        # it the epitope residues on that chain.
        reduced = antigen_assembly(target, antigen_chains)
        if reduced is not None:
            return reduced, True
    plain = antigen_only(target, antigen_chains)
    # The AU's assembly list still names the antibody chains we dropped, which
    # makes expand_assembly raise downstream. Clearing it also makes
    # check_burial emit NO_ASSEMBLY_DEFINED, which is the truth here.
    plain.st.assemblies.clear()
    return plain, False


@dataclass(frozen=True)
class StructureLocator:
    """Shared base for arms that read coordinates from a directory.

    Holds the directory and the per-run tallies. A frozen dataclass with a
    mutable ``stats`` dict is deliberate: arm pairing matches predictors by
    object identity, so the object must stay stable while counters accumulate.
    """

    structure_dir: Path

    def locate(self, pdb_id: str) -> Path | None:
        return locate_structure(self.structure_dir, pdb_id)
