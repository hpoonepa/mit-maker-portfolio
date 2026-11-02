# SPDX-License-Identifier: MIT
"""Structure loading, numbering maps, and unmodelled-residue detection.

Two things here are load-bearing and easy to get wrong.

**Declared is not observed.** An mmCIF entry declares the full polymer sequence
in ``_entity_poly_seq`` and separately lists the atoms that were actually seen.
Flexible regions routinely appear in the first and not the second. Designing a
binder against a residue with no coordinates is designing against nothing.

**The optional category.** ``_pdbx_unobs_or_zero_occ_residues`` declares exactly
which residues are unmodelled, but it is **not mandatory and is absent from many
entries**. Code that trusts it alone reports "nothing missing" on an entry with
plenty missing. So we compute the answer two independent ways and cross-check:
read the category when it exists, and separately derive the gap by comparing the
declared sequence against observed coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gemmi

from .residue import NO_ICODE, ResidueKey

__all__ = [
    "Target",
    "load_target",
    "build_label_seq_map",
    "declared_residues",
    "observed_residues",
    "unobserved_from_cif_category",
    "unobserved_from_alignment",
    "low_occupancy_residues",
    "NumberingWarning",
]

LOW_OCCUPANCY_THRESHOLD = 0.5
"""Occupancy at or below this is treated as effectively unobserved."""


class NumberingWarning(UserWarning):
    """Author numbering could not be reconciled with label numbering."""


def _icode(raw: str) -> str:
    """Normalise gemmi's insertion code to the mmCIF single-space convention."""
    if raw is None or raw in ("", "\x00", "?", "."):
        return NO_ICODE
    return raw


@dataclass
class Target:
    """A loaded structure plus its raw cif block.

    Both are kept because the object model and the raw categories answer
    different questions: gemmi's model knows about coordinates and assemblies,
    while categories like ``_pdbx_unobs_or_zero_occ_residues`` and
    ``_pdbx_poly_seq_scheme`` exist only in the cif text.
    """

    path: Path
    st: gemmi.Structure
    block: gemmi.cif.Block

    @property
    def chain_ids(self) -> list[str]:
        """Author chain identifiers of polymer chains, in file order."""
        out: list[str] = []
        for chain in self.st[0]:
            if len(chain.get_polymer()) and chain.name not in out:
                out.append(chain.name)
        return out

    @property
    def entry_id(self) -> str:
        return self.st.name or self.path.stem


def load_target(path: str | Path) -> Target:
    """Read an mmCIF or PDB file into a :class:`Target`.

    Only model 1 is used. Multi-model entries (NMR ensembles) are common and
    their later models are alternative conformers, not additional content; any
    per-residue verdict would be ambiguous across them.
    """
    path = Path(path)
    st = gemmi.read_structure(str(path))
    st.setup_entities()
    st.remove_alternative_conformations()
    while len(st) > 1:
        del st[1]
    doc = gemmi.cif.read(str(path))
    return Target(path=path, st=st, block=doc.sole_block())


def observed_residues(target: Target) -> set[ResidueKey]:
    """Polymer residues that have at least one atom in the coordinates."""
    out: set[ResidueKey] = set()
    for chain in target.st[0]:
        for res in chain.get_polymer():
            if len(res):
                out.add(
                    ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode))
                )
    return out


def low_occupancy_residues(target: Target) -> set[ResidueKey]:
    """Residues whose every atom sits at or below the occupancy threshold.

    A residue modelled at zero occupancy is present in the file but was not
    actually resolved, so it warrants the same suspicion as a missing one.
    """
    out: set[ResidueKey] = set()
    for chain in target.st[0]:
        for res in chain.get_polymer():
            if not len(res):
                continue
            if max(atom.occ for atom in res) <= LOW_OCCUPANCY_THRESHOLD:
                out.add(
                    ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode))
                )
    return out


def build_label_seq_map(target: Target) -> dict[ResidueKey, int]:
    """Map author numbering to mmCIF ``label_seq_id`` for observed residues.

    This is the conversion BoltzGen needs. It is built only from observed
    coordinates, so an unmodelled residue is necessarily absent — which is why
    :func:`hotspot_preflight.residue.to_boltzgen` raises rather than guessing
    when a key is missing.
    """
    out: dict[ResidueKey, int] = {}
    for chain in target.st[0]:
        for res in chain.get_polymer():
            if not len(res) or res.label_seq is None:
                continue
            key = ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode))
            out[key] = int(res.label_seq)
    return out


def _poly_seq_scheme(target: Target) -> dict[tuple[str, int], tuple[int, str]]:
    """Read ``_pdbx_poly_seq_scheme``: the authoritative label↔author mapping.

    This category covers every declared residue, modelled or not, which is
    exactly what we need to name an unmodelled residue in author numbering.
    Returns ``{(auth_asym_id, label_seq): (auth_seq, icode)}``.
    """
    tab = target.block.find(
        "_pdbx_poly_seq_scheme.",
        ["pdb_strand_id", "seq_id", "?pdb_seq_num", "?auth_seq_num", "?pdb_ins_code"],
    )
    out: dict[tuple[str, int], tuple[int, str]] = {}
    for row in tab:
        # Column preference is not cosmetic. Verified on 6F5J: for residues that
        # are declared but unmodelled, `auth_seq_num` is EMPTY while
        # `pdb_seq_num` carries the number. Reading auth_seq_num first and
        # skipping blanks therefore drops precisely the residues this whole
        # module exists to find.
        #   strand=C seq_id=398 auth_seq_num='398' pdb_seq_num='398'  (modelled)
        #   strand=C seq_id=399 auth_seq_num=''    pdb_seq_num='399'  (unmodelled)
        num_raw = ""
        for idx in (2, 3):
            if row.has(idx) and row.str(idx) not in ("?", ".", ""):
                num_raw = row.str(idx)
                break
        if not num_raw:
            continue
        icode = _icode(row.str(4)) if row.has(4) else NO_ICODE
        try:
            out[(row.str(0), int(row.str(1)))] = (int(num_raw), icode)
        except ValueError:
            continue
    return out


def declared_residues(target: Target) -> set[ResidueKey]:
    """Every residue the entry declares, modelled or not, in author numbering.

    Prefers ``_pdbx_poly_seq_scheme``, which states the author number for every
    declared residue. When that category is absent, derives the author number by
    finding the constant label→author offset implied by the observed residues of
    each chain. If a chain's offset is not constant — renumbering, insertion
    codes mid-chain — that chain's unmodelled residues cannot be named reliably
    and are omitted rather than guessed at; the resolved check reports the
    reduced confidence instead of inventing a number.
    """
    scheme = _poly_seq_scheme(target)
    if scheme:
        return {
            ResidueKey(chain_id, auth_num, icode)
            for (chain_id, _label), (auth_num, icode) in scheme.items()
        }
    return _declared_by_offset(target)


def _entity_for_subchain(st: gemmi.Structure, subchain_id: str) -> gemmi.Entity | None:
    """Find the entity owning a subchain.

    Not `st.get_entity(...)`: that looks up by entity *name* and returns None
    when handed a subchain id, which fails silently and leaves the declared
    sequence unreadable. Entity names and subchain ids differ — a chain's
    subchain may be 'Axp' while its entity is named 'A'.
    """
    for entity in st.entities:
        if subchain_id in entity.subchains:
            return entity
    return None


def _declared_by_offset(target: Target) -> set[ResidueKey]:
    out: set[ResidueKey] = set()
    for chain in target.st[0]:
        polymer = chain.get_polymer()
        if not len(polymer):
            continue
        entity = _entity_for_subchain(target.st, polymer.subchain_id())
        if entity is None or not len(entity.full_sequence):
            continue

        offsets = {
            res.seqid.num - int(res.label_seq)
            for res in polymer
            if len(res) and res.label_seq is not None
        }
        if len(offsets) != 1:
            # Numbering is not a simple shift; naming the gaps would be a guess.
            continue
        offset = offsets.pop()
        for label_seq in range(1, len(entity.full_sequence) + 1):
            out.add(ResidueKey(chain.name, label_seq + offset, NO_ICODE))
    return out


def unobserved_from_cif_category(target: Target) -> set[ResidueKey] | None:
    """Read ``_pdbx_unobs_or_zero_occ_residues``, the entry's own declaration.

    Returns:
        The declared unmodelled residues, or ``None`` when the category is
        absent. ``None`` and ``set()`` mean different things: *the entry does not
        say* versus *the entry says nothing is missing*. Collapsing them is the
        bug that makes a checker silently useless on about half of the archive.
    """
    tab = target.block.find(
        "_pdbx_unobs_or_zero_occ_residues.",
        ["auth_asym_id", "auth_seq_id", "?PDB_ins_code"],
    )
    if not tab:
        return None
    out: set[ResidueKey] = set()
    for row in tab:
        try:
            num = int(row.str(1))
        except ValueError:
            continue
        icode = _icode(row.str(2)) if row.has(2) else NO_ICODE
        out.add(ResidueKey(row.str(0), num, icode))
    return out


def unobserved_from_alignment(target: Target) -> set[ResidueKey]:
    """Derive unmodelled residues independently of the optional category.

    This is declared-minus-observed: the same answer the category gives, reached
    by comparing the declared polymer sequence against the coordinates. It works
    on entries that omit the category, and on entries that have it, the two
    routes are cross-checked against each other — disagreement is itself
    reportable, since it means the deposition is internally inconsistent.
    """
    return declared_residues(target) - observed_residues(target)
