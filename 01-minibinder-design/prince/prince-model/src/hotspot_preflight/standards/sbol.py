# SPDX-License-Identifier: MIT
"""SBOL 3 adapter: annotate a PDB-derived protein, correctly.

**Why this module exists, and why it is not decoration.**

An SBOL ``Range`` "specifies a region via discrete, inclusive start and end
positions that correspond to indices for characters in the ``elements`` String
of a Sequence" (SBOL 3.1.0, ``location.tex``), and those elements "could
represent ... the amino acid residues of a protein" (``sequence.tex``). So
``Range`` is not nucleotide-specific, and it is **1-based inclusive**.

That is the whole problem. A ``Range`` indexes the *stored sequence string*.
PDB author numbering has offsets, gaps and insertion codes, so an author
residue number is **not** a string index — on 6F5J chain C they happen to
coincide, and on a chain numbered from 101 with two unmodelled residues in the
middle they do not. Writing author numbers into a ``Range`` produces a document
that validates cleanly and points at the wrong amino acids.

Annotating a PDB-derived protein in SBOL therefore *requires* exactly the
numbering layer this package already is. This module is that adapter, nothing
more: :func:`sequence_index_map` is the conversion, and everything else is
serialisation around it.

**Which sequence we index against: the declared one.**

:func:`chain_sequence` returns the *declared* polymer sequence — mmCIF
``_entity_poly_seq`` / SEQRES — including residues that have no coordinates,
because an SBOL ``Component`` describes a molecule rather than a crystal.
Indexing the observed sequence instead would tie a residue's index to which
loops that particular experiment happened to resolve, so the same residue
would carry different ``Range`` values in two entries of the same protein. It
would also throw away the anchor: against the declared sequence the index *is*
the mmCIF ``label_seq_id``, which the file already states.

So an unmodelled hotspot still gets a correct ``Range``. That is intended —
whether a residue was resolved is the resolved check's verdict to deliver, not
something to encode by silently shifting an index. A hotspot that cannot be
mapped at all raises :class:`NumberingMapError`; no guessed index is ever
emitted.

**The role URI is ours, and is a proposal.**

There is **no Sequence Ontology or Gene Ontology term for a binding hotspot
residue**, and no documented example of SBOL being used to annotate a protein
residue was found in the specification, the SEPs or the issue tracker.
:data:`HOTSPOT_ROLE_URI` and :data:`CONSTRUCT_ROLE_URI` are therefore
**conventions proposed by this project**, not existing standards. They are
minted as ``tag:`` URIs (RFC 4151) because that scheme exists for identifiers
that are owned but deliberately not resolvable, so neither can be mistaken for
an ontology lookup. The relevant open standards work is **SEP 033**
(non-canonical proteins); if a real term is ever minted, retire these.

Nothing in this module claims anything about iGEM part-submission requirements.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import gemmi

from ..residue import NO_ICODE, ResidueKey
from ..structure import Target, _icode, _poly_seq_scheme

if TYPE_CHECKING:  # pragma: no cover - typing only
    import sbol3

__all__ = [
    "HOTSPOT_ROLE_URI",
    "CONSTRUCT_ROLE_URI",
    "DEFAULT_NAMESPACE",
    "SbolUnavailableError",
    "NumberingMapError",
    "ConstructReadError",
    "sbol3_available",
    "sequence_index_map",
    "chain_sequence",
    "write_sbol",
    "read_construct",
    "construct_crop_range",
]

HOTSPOT_ROLE_URI = (
    "tag:lambert-igem-2026,2026-10-05:hotspot-preflight/binding_hotspot_residue"
)
"""A convention **proposed by this project**, not an existing ontology term.

No SO or GO term for "binding hotspot residue" exists. A ``tag:`` URI
(RFC 4151) so it is plainly ours and plainly not resolvable. See SEP 033.
"""

CONSTRUCT_ROLE_URI = (
    "tag:lambert-igem-2026,2026-10-05:hotspot-preflight/expressed_region"
)
"""Also ours, also proposed. Marks the ``Range`` that delimits the construct."""

DEFAULT_NAMESPACE = "https://gitlab.igem.org/2026/software/hotspot-preflight"
"""Placeholder namespace. SBOL namespaces are identifiers and need not
resolve; callers publishing documents should pass their own."""

_COMPONENT_PREFIX = "target_"
"""Component displayId prefix. SBOL displayIds may not start with a digit and
every PDB id does, so the chain cannot simply be appended to the entry id."""


class SbolUnavailableError(ImportError):
    """``sbol3`` is not installed."""


class NumberingMapError(ValueError):
    """A residue could not be converted to a sequence index."""


class ConstructReadError(ValueError):
    """An SBOL document does not unambiguously describe one construct range."""


def sbol3_available() -> bool:
    """Whether the optional ``sbol3`` dependency can be imported."""
    try:
        _require_sbol3()
    except SbolUnavailableError:
        return False
    return True


def _require_sbol3() -> "sbol3":
    """Import ``sbol3`` on demand, so the core installs and runs without it."""
    try:
        import sbol3
    except ImportError as exc:
        raise SbolUnavailableError(
            "SBOL output needs the optional 'sbol3' dependency, which is not "
            "installed. Install it with:  pip install 'hotspot-preflight[sbol]'"
        ) from exc
    return sbol3


# --- The numbering layer -------------------------------------------------


def _polymer_entity(target: Target, chain_id: str) -> gemmi.Entity:
    """The entity whose declared sequence backs ``chain_id``."""
    for chain in target.st[0]:
        polymer = chain.get_polymer()
        if chain.name != chain_id or not len(polymer):
            continue
        subchain = polymer.subchain_id()
        for entity in target.st.entities:
            if subchain not in entity.subchains:
                continue
            if not len(entity.full_sequence):
                raise NumberingMapError(
                    f"chain {chain_id!r} of {target.entry_id} declares no "
                    f"polymer sequence, so there is no string to index: the "
                    f"entry is missing _entity_poly_seq / SEQRES."
                )
            return entity
    raise NumberingMapError(
        f"chain {chain_id!r} is not a polymer chain of {target.entry_id}; "
        f"available chains: {', '.join(target.chain_ids) or '(none)'}"
    )


def chain_sequence(target: Target, chain_id: str) -> str:
    """One-letter declared sequence of ``chain_id``, in ``label_seq_id`` order.

    The string an SBOL ``Range`` indexes, so it must stay exactly in step with
    :func:`sequence_index_map`. Unmodelled residues are included — see the
    module docstring. Non-standard and unknown monomers become ``X`` rather
    than being dropped, since dropping one shifts every index after it.
    """
    letters: list[str] = []
    for item in _polymer_entity(target, chain_id).full_sequence:
        # Microheterogeneity is written "ALA,SER"; the first monomer is the one
        # the index refers to.
        info = gemmi.find_tabulated_residue(gemmi.Entity.first_mon(item) or item)
        usable = info is not None and info.is_amino_acid()
        letters.append(info.one_letter_code.upper() if usable else "X")
    return "".join(letters)


def sequence_index_map(target: Target, chain_id: str) -> dict[ResidueKey, int]:
    """Author numbering to 1-based index into :func:`chain_sequence`.

    The conversion the SBOL specification makes necessary and that no SBOL
    library can do for you, because it needs the mmCIF numbering categories.
    Since the indexed string is the *declared* sequence, the index returned is
    the mmCIF ``label_seq_id``. Two routes produce it, in order of authority:
    ``_pdbx_poly_seq_scheme``, which states the author number for every
    declared residue, modelled or not; failing that, the constant
    label-to-author offset implied by the chain's observed residues — see
    :func:`_map_by_offset`.

    Raises:
        NumberingMapError: if the chain is not a polymer chain, or declares no
            sequence.
    """
    entity = _polymer_entity(target, chain_id)
    n_declared = len(entity.full_sequence)

    scheme = {
        label: author
        for (strand, label), author in _poly_seq_scheme(target).items()
        if strand == chain_id
    }
    if scheme:
        return {
            ResidueKey(chain_id, num, icode): label
            for label, (num, icode) in scheme.items()
            if 1 <= label <= n_declared
        }

    return _map_by_offset(target, chain_id, n_declared)


def _map_by_offset(
    target: Target, chain_id: str, n_declared: int
) -> dict[ResidueKey, int]:
    """Fallback for files without ``_pdbx_poly_seq_scheme``.

    gemmi's own mmCIF writer omits that category, so this path is exercised by
    every file this package writes as well as by sparse depositions.
    """
    observed: dict[int, ResidueKey] = {}
    for chain in target.st[0]:
        if chain.name != chain_id:
            continue
        for res in chain.get_polymer():
            if not len(res) or res.label_seq is None:
                continue
            observed[int(res.label_seq)] = ResidueKey(
                chain_id, res.seqid.num, _icode(res.seqid.icode)
            )

    offsets = {key.auth_seq_id - label for label, key in observed.items()}
    if len(offsets) == 1:
        offset = offsets.pop()
        return {
            ResidueKey(chain_id, label + offset, NO_ICODE): label
            for label in range(1, n_declared + 1)
        }

    # Numbering is not a simple shift. Name only what the coordinates name;
    # write_sbol will refuse anything else by hand rather than guess.
    return {key: label for label, key in observed.items()}


# --- Out: hotspots as SequenceFeature + Range ----------------------------


def _check_display_id(chain_id: str) -> None:
    if not chain_id or not all(c.isalnum() or c == "_" for c in chain_id):
        raise NumberingMapError(
            f"chain id {chain_id!r} cannot be used in an SBOL displayId, which "
            f"must be alphanumeric or underscore"
        )


def write_sbol(
    target: Target,
    chain_id: str,
    keys: Sequence[ResidueKey],
    path: str | Path,
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> None:
    """Write one chain as an SBOL 3 ``Component`` with its hotspots annotated.

    The document holds a ``Sequence`` with the declared one-letter chain
    sequence (``sbol3.IUPAC_PROTEIN_ENCODING``); a ``Component`` of type
    ``sbol3.SBO_PROTEIN`` referencing it, with ``displayId`` ``target_<chain>``
    so :func:`read_construct` can recover the chain; one single-residue
    ``SequenceFeature`` of role :data:`HOTSPOT_ROLE_URI` per hotspot, named
    ``hotspot_<author key>``; and one of role :data:`CONSTRUCT_ROLE_URI`
    spanning the whole stored sequence — the construct, which is what the
    burial check consumes as its crop.

    Feature names and descriptions keep author numbering beside the index, so
    a reader can check the conversion instead of trusting it.

    Raises:
        SbolUnavailableError: if ``sbol3`` is not installed.
        NumberingMapError: if ``keys`` is empty, if any key is on another
            chain, or if any key has no sequence index. An unmappable hotspot
            is an error, never a skipped feature or a guessed number.
        ValueError: if the written document fails SBOL validation.
    """
    sbol3 = _require_sbol3()
    _check_display_id(chain_id)

    if not keys:
        raise NumberingMapError("no hotspot residues to write")
    wrong_chain = [k for k in keys if k.auth_asym_id != chain_id]
    if wrong_chain:
        raise NumberingMapError(
            f"hotspots {', '.join(str(k) for k in wrong_chain)} are not on "
            f"chain {chain_id!r}; write one document per chain"
        )

    elements = chain_sequence(target, chain_id)
    index_map = sequence_index_map(target, chain_id)
    missing = [k for k in keys if k not in index_map]
    if missing:
        raise NumberingMapError(
            f"cannot map {', '.join(str(k) for k in missing)} to a position in "
            f"the declared sequence of chain {chain_id!r} "
            f"({len(elements)} residues). These residues are not declared by "
            f"{target.entry_id}, or the chain's numbering could not be "
            f"reconciled. Refusing to emit an index that would point at the "
            f"wrong amino acid."
        )

    base = namespace.rstrip("/")
    sequence = sbol3.Sequence(
        f"{base}/{_COMPONENT_PREFIX}{chain_id}_sequence",
        elements=elements,
        encoding=sbol3.IUPAC_PROTEIN_ENCODING,
        namespace=base,
    )
    component = sbol3.Component(
        f"{base}/{_COMPONENT_PREFIX}{chain_id}",
        sbol3.SBO_PROTEIN,
        sequences=[sequence],
        namespace=base,
        description=(
            f"{target.entry_id} chain {chain_id}, declared sequence. Range "
            f"positions are 1-based indices into that sequence, not author "
            f"residue numbers."
        ),
    )

    def feature(first: int, last: int, name: str, role: str, note: str):
        return sbol3.SequenceFeature(
            locations=[sbol3.Range(sequence, first, last)],
            name=name,
            roles=[role],
            description=note,
        )

    component.features.append(
        feature(
            1,
            len(elements),
            "expressed_region",
            CONSTRUCT_ROLE_URI,
            "The construct: the region of the declared sequence described here.",
        )
    )
    for key in keys:
        index = index_map[key]
        component.features.append(
            feature(
                index,
                index,
                f"hotspot_{key}",
                HOTSPOT_ROLE_URI,
                f"author {key} -> sequence index {index} ({elements[index - 1]})",
            )
        )

    doc = sbol3.Document()
    doc.add(sequence)
    doc.add(component)
    report = doc.validate()
    if report.errors:
        raise ValueError(
            "generated SBOL document failed validation: "
            + "; ".join(str(e) for e in report.errors)
        )
    # SORTED_NTRIPLES so that two runs on the same input are byte-identical,
    # which is what makes the run record reproducible.
    doc.write(str(path), sbol3.SORTED_NTRIPLES)


# --- In: the construct is the crop ---------------------------------------


def read_construct(path: str | Path) -> tuple[str, int, int]:
    """Read the expressed region from an SBOL document.

    Returns:
        ``(identifier, first, last)``. ``first`` and ``last`` are **1-based
        indices into the document's own Sequence**, SBOL's native coordinate
        system; ``identifier`` is the chain id for documents written by
        :func:`write_sbol`, otherwise the ``Component``'s ``displayId``.

    .. warning::
        ``first`` and ``last`` are **not author residue numbers**, yet the
        tuple has the same shape as ``check_burial``'s ``crop_range``, which
        takes author numbers — passing it straight through is exactly the
        silent misaim this package exists to prevent. Use
        :func:`construct_crop_range`, which converts against a structure.

    The range comes from the single non-hotspot ``SequenceFeature`` carrying a
    ``Range`` location.

    Raises:
        SbolUnavailableError: if ``sbol3`` is not installed.
        ConstructReadError: if the document holds no such feature, more than
            one, or more than one sequence-bearing ``Component``. An ambiguous
            document is reported, not resolved by picking one.
    """
    sbol3 = _require_sbol3()
    doc = sbol3.Document()
    doc.read(str(path))

    components = [
        o for o in doc.objects if isinstance(o, sbol3.Component) and o.sequences
    ]
    if not components:
        raise ConstructReadError(
            f"{path}: no SBOL Component with a Sequence. A construct document "
            f"must carry the sequence its range indexes."
        )
    if len(components) > 1:
        names = ", ".join(c.display_id for c in components)
        raise ConstructReadError(
            f"{path}: {len(components)} Components carry sequences ({names}); "
            f"which one is the construct is ambiguous. Split the document, or "
            f"supply the crop range directly."
        )
    component = components[0]

    ranges: list[tuple[str, int, int]] = []
    for feature in component.features:
        if HOTSPOT_ROLE_URI in getattr(feature, "roles", []):
            continue
        for location in getattr(feature, "locations", []):
            if isinstance(location, sbol3.Range):
                ranges.append((feature.name or "", location.start, location.end))

    if not ranges:
        raise ConstructReadError(
            f"{path}: Component {component.display_id!r} has no SequenceFeature "
            f"with a Range delimiting the expressed region, so the construct "
            f"boundary is not stated. Add one (role "
            f"{CONSTRUCT_ROLE_URI}), or pass the crop range explicitly."
        )
    if len(ranges) > 1:
        described = ", ".join(f"{name or '?'}:{a}-{b}" for name, a, b in ranges)
        raise ConstructReadError(
            f"{path}: {len(ranges)} candidate construct ranges ({described}). "
            f"Which one is the expressed region is ambiguous; leave exactly one "
            f"non-hotspot Range, or pass the crop range explicitly."
        )

    _, first, last = ranges[0]
    if first > last:
        raise ConstructReadError(f"{path}: construct range {first}-{last} is backwards")

    identifier = component.display_id
    if identifier.startswith(_COMPONENT_PREFIX):
        identifier = identifier[len(_COMPONENT_PREFIX) :]
    return identifier, int(first), int(last)


def construct_crop_range(
    target: Target, chain_id: str, path: str | Path
) -> tuple[str, int, int]:
    """Read a construct and return it as an author-numbered crop range.

    This is the safe form of :func:`read_construct`: the result can be handed
    straight to :func:`hotspot_preflight.checks.burial.check_burial` as
    ``crop_range``, because the sequence indices have been converted back to
    the author numbering that function expects.

    Raises:
        ConstructReadError: if the document's range falls outside the chain's
            declared sequence, if either endpoint has no author number, or if
            the document names a different chain of this same structure.
    """
    identifier, first, last = read_construct(path)
    if identifier != chain_id and identifier in target.chain_ids:
        raise ConstructReadError(
            f"{path} describes chain {identifier!r} of {target.entry_id}, not "
            f"the requested chain {chain_id!r}"
        )

    by_index = {i: k for k, i in sequence_index_map(target, chain_id).items()}
    n_declared = len(chain_sequence(target, chain_id))
    if not (1 <= first <= last <= n_declared):
        raise ConstructReadError(
            f"{path}: construct range {first}-{last} does not fit the declared "
            f"sequence of {target.entry_id} chain {chain_id} "
            f"({n_declared} residues). The document probably describes a "
            f"different protein."
        )

    unknown = [i for i in (first, last) if i not in by_index]
    if unknown:
        raise ConstructReadError(
            f"{path}: no author residue number for sequence index "
            f"{', '.join(str(i) for i in unknown)} of {target.entry_id} chain "
            f"{chain_id}: the chain's numbering could not be reconciled, so "
            f"converting the crop would be a guess."
        )

    return chain_id, by_index[first].auth_seq_id, by_index[last].auth_seq_id
