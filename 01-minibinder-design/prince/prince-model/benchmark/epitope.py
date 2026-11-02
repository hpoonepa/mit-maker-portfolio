# SPDX-License-Identifier: MIT
"""Deriving epitope residues from antibody-antigen coordinates.

The definition, which is the AsEP/PECAN convention and is fixed here as module
constants so no caller can quietly change it:

    An antigen residue is in the epitope when its minimum heavy-atom (non-H)
    distance to any heavy atom of any antibody chain of that instance is
    <= 4.5 A, measured on the **deposited asymmetric unit**, after removing
    hydrogens, alternate conformations and zero-occupancy atoms, with the
    antibody atom set restricted to amino acids.

4.0 A (the DiscoTope-3.0 / BepiPred-3.0 convention) is supported as a
sensitivity analysis. SEMA's 8 A / 16 A-mask convention is **not comparable**
and must not be compared against.

**Why scipy and not gemmi.** ``gemmi.NeighborSearch`` applies crystal symmetry
by default. On a crystal structure that means a symmetry mate of the antibody,
sitting across a lattice contact, is reported as touching the antigen — so
residues on the far side of the antigen enter the epitope label and nothing
anywhere raises an error. ``scipy.spatial.cKDTree`` knows nothing about
symmetry, which is exactly the property we want. :func:`epitope` is therefore
written against cKDTree and ``tests/test_benchmark.py`` pins that choice.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import gemmi
import numpy as np
from scipy.spatial import cKDTree

from hotspot_preflight.residue import NO_ICODE, ResidueKey
from hotspot_preflight.structure import Target, load_target

__all__ = [
    "EPITOPE_CUTOFF_A",
    "SENSITIVITY_CUTOFF_A",
    "MIN_EPITOPE_RESIDUES",
    "EmptyAntibodyAtomSet",
    "NoAntigenAtoms",
    "AntigenIsAntibodyChain",
    "AtomSet",
    "EpitopeResult",
    "heavy_atoms",
    "protein_chain_ids",
    "epitope",
    "RCSB_COORDINATE_URL",
    "CoordinateFetchError",
    "cached_structure",
    "resolve_chain",
    "resolve_chains",
    "NAMESPACES",
    "USABLE_NAMESPACES",
    "REFUSED_NAMESPACES",
    "ChainNamespaces",
    "ChainResolution",
    "chain_namespaces",
    "resolve_antigen_chains",
]

EPITOPE_CUTOFF_A = 4.5
"""Primary cutoff. Do not change without re-running every validation target."""

SENSITIVITY_CUTOFF_A = 4.0
"""Secondary cutoff, reported alongside the primary as a sensitivity analysis."""

MIN_EPITOPE_RESIDUES = 5
"""Guard 3: below this, the 'epitope' is a packing artefact, not an interface.

Entries under the floor are dropped from the benchmark and **logged by id with
their size**, never dropped silently, because a systematic cause (wrong antigen
chain, symmetry contact, partial occupancy) looks exactly like a handful of
legitimately tiny interfaces until you read the list.
"""

_KDTREE_SLACK = 0.01
"""cKDTree's ``distance_upper_bound`` is exclusive in effect for float ties.

Querying at ``cutoff + 0.01`` and then not re-filtering means a contact at
exactly 4.5 A is kept, which is what '<= 4.5' means. The slack is far below
coordinate precision (0.001 A in mmCIF) so it cannot admit a 4.51 A contact
that rounding would not already have made ambiguous.
"""

RCSB_COORDINATE_URL = "https://files.rcsb.org/download/{pdb_id}.cif.gz"
"""Note: the path is case-sensitive and wants the **uppercase** 4-char id.

Also note ``HTTP HEAD`` against files.rcsb.org is blocked (0/40 attempts in the
probe), so existence checks must use GET. We never check existence separately —
we fetch into the cache and let the fetch itself be the check.
"""


class EmptyAntibodyAtomSet(ValueError):
    """The antibody chains resolved to no atoms at all.

    Guard 1's assertion. Without it, an unresolved scFv chain name (``'H1'``
    where the chain is ``'H'``) yields an empty query tree and therefore an
    empty epitope, which looks like a legitimately tiny interface and is
    silently excluded by the size floor rather than reported as the bug it is.
    """


class NoAntigenAtoms(ValueError):
    """No protein-typed antigen chain of this instance exists in the file."""


class AntigenIsAntibodyChain(ValueError):
    """An antigen chain is also an antibody chain of the same instance.

    Guard 5's assertion, and the reason it exists: 1MHP's annotated antigen
    ``C`` is the ``label_asym_id`` of auth chain ``L`` — the Fab's own **light
    chain**. Resolving ``C`` without this check puts the antibody into its own
    antigen set, and the resulting "epitope" is the light-chain residues within
    4.5 A of the heavy chain: a few dozen plausible-looking residues of the
    wrong molecule entirely.

    :func:`resolve_antigen_chains` refuses such a candidate and records it, so
    the driver never constructs this call. Reaching :func:`epitope` with one
    means a caller bypassed the resolver, which is a bug, not a structure.
    """


class CoordinateFetchError(RuntimeError):
    """Coordinates could not be obtained; the message says which id and why."""


@dataclass(frozen=True)
class AtomSet:
    """Heavy-atom coordinates plus the residue each atom belongs to.

    ``coords`` is ``(n_atoms, 3)`` float64 and ``owners[i]`` is the residue of
    ``coords[i]``. Keeping them as parallel arrays rather than per-residue
    groups is what lets one cKDTree query answer the whole structure at once.
    """

    coords: np.ndarray
    owners: tuple[ResidueKey, ...]

    def __len__(self) -> int:
        return int(self.coords.shape[0])


def _is_amino_acid(residue: gemmi.Residue) -> bool:
    """True for the 20 standard residues and tabulated modified amino acids.

    Uses gemmi's chemical-component table rather than a hardcoded list, so that
    selenomethionine, pyroglutamate (6AL0 chain L starts with PCA) and the rest
    of the modified-residue tail are counted as protein instead of ligand.
    """
    info = gemmi.find_tabulated_residue(residue.name)
    return info is not None and info.is_amino_acid()


def _is_hydrogen(atom: gemmi.Atom) -> bool:
    return atom.element.name in ("H", "D")


def heavy_atoms(
    target: Target,
    chain_ids: Iterable[str],
    amino_acids_only: bool = True,
) -> AtomSet:
    """Collect heavy, occupied atoms of the named chains.

    Args:
        target: loaded by :func:`hotspot_preflight.structure.load_target`, which
            has already dropped models 2+ and alternate conformations.
        chain_ids: **resolved** auth chain ids, not raw summary-table values.
        amino_acids_only: restrict to amino-acid residues. True for the antibody
            side by definition, and True for the antigen side as well so that a
            bound ion or sugar in the same auth chain cannot enter the label.

    Waters are excluded by the amino-acid test; when ``amino_acids_only`` is
    False they are excluded explicitly, since a bridging water is not a contact.
    """
    wanted = set(chain_ids)
    coords: list[tuple[float, float, float]] = []
    owners: list[ResidueKey] = []
    for chain in target.st[0]:
        if chain.name not in wanted:
            continue
        for residue in chain:
            if amino_acids_only:
                if not _is_amino_acid(residue):
                    continue
            elif residue.name == "HOH":
                continue
            key = ResidueKey(
                chain.name, residue.seqid.num, _normalise_icode(residue.seqid.icode)
            )
            for atom in residue:
                if _is_hydrogen(atom) or atom.occ <= 0.0:
                    continue
                coords.append((atom.pos.x, atom.pos.y, atom.pos.z))
                owners.append(key)
    array = (
        np.asarray(coords, dtype=np.float64)
        if coords
        else np.empty((0, 3), dtype=np.float64)
    )
    return AtomSet(coords=array, owners=tuple(owners))


def _normalise_icode(raw: str) -> str:
    """gemmi reports 'no insertion code' several ways; ResidueKey wants one."""
    if raw is None or raw in ("", "\x00", "?", "."):
        return NO_ICODE
    return raw


def protein_chain_ids(target: Target, min_residues: int = 1) -> set[str]:
    """Auth chain ids containing at least ``min_residues`` amino acids.

    Chain typing is done here, from the coordinates, and **not** from SAbDab's
    ``antigen_type`` field. The reason is that ``antigen_chain`` and
    ``antigen_type`` are not positionally aligned: 1BJ1 lists three antigen
    chains ``A|V|W`` against two types ``ION|PROTEIN``, so zipping them assigns
    the wrong type to the wrong chain. The structure cannot lie about this.
    """
    out: set[str] = set()
    for chain in target.st[0]:
        count = sum(1 for residue in chain if _is_amino_acid(residue))
        if count >= min_residues:
            out.add(chain.name)
    return out


@dataclass(frozen=True)
class EpitopeResult:
    """The epitope of one antibody instance, with its per-chain breakdown.

    ``residues`` is the union over every protein-typed antigen chain, which is
    guard 2: picking a single antigen chain picks the wrong one often enough to
    matter (1BJ1 chain V alone gives a 2-residue epitope at the wrong site).

    ``per_chain`` is kept because the union is not always the quantity you want
    to compare against a published epitope. On 1BJ1 the union is 19 residues:
    the canonical 17-residue bevacizumab epitope on chain W, plus 2 residues on
    the second VEGF monomer V that the Fab also grazes. Both numbers are
    correct; they answer different questions. ``dominant_chain`` names the chain
    carrying the most contacts, which is the one a published epitope refers to.
    """

    instance_id: str
    pdb_id: str
    antibody_chains: tuple[str, ...]
    antigen_chains: tuple[str, ...]
    residues: tuple[ResidueKey, ...]
    per_chain: Mapping[str, tuple[ResidueKey, ...]]
    dominant_chain: str | None
    cutoff: float
    n_antibody_atoms: int
    n_antigen_atoms: int
    unresolved_chains: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return len(self.residues)

    @property
    def passes_size_floor(self) -> bool:
        return self.size >= MIN_EPITOPE_RESIDUES

    @property
    def dominant_residues(self) -> tuple[ResidueKey, ...]:
        if self.dominant_chain is None:
            return ()
        return tuple(self.per_chain[self.dominant_chain])


def epitope(
    target: Target,
    instance_id: str,
    antibody_chains: Sequence[str],
    antigen_chains: Sequence[str],
    cutoff: float = EPITOPE_CUTOFF_A,
) -> EpitopeResult:
    """Derive the epitope of one antibody instance.

    Args:
        antibody_chains: resolved auth chain ids of the heavy and light chains.
            For a VHH there is only one.
        antigen_chains: resolved auth chain ids of the antigen. Non-protein
            chains are filtered out here, and the contacts of every remaining
            chain are unioned.

    Raises:
        EmptyAntibodyAtomSet: the antibody side has no atoms. Always a naming
            bug, never a property of the structure.
        NoAntigenAtoms: no protein-typed antigen chain survived filtering.
        AntigenIsAntibodyChain: an antigen chain is also an antibody chain.
            Guard 5. This used to be filtered out silently, which meant a
            caller could hand over the Fab's own light chain as the antigen and
            get back a confident, wrong label — or, when it was the only
            antigen chain, a ``NoAntigenAtoms`` blaming the structure for a
            resolution bug.
    """
    protein = protein_chain_ids(target)
    ab_chains = tuple(c for c in dict.fromkeys(antibody_chains) if c in protein)
    overlap = [c for c in dict.fromkeys(antigen_chains) if c in ab_chains]
    if overlap:
        raise AntigenIsAntibodyChain(
            f"{instance_id}: antigen chain(s) {overlap} are also antibody chains "
            f"of this instance (antibody {list(ab_chains)}) in {target.entry_id}. "
            f"The epitope would be measured against the antibody itself. Resolve "
            f"antigen chains with resolve_antigen_chains(), which refuses this."
        )
    ag_chains = tuple(
        c for c in dict.fromkeys(antigen_chains) if c in protein and c not in ab_chains
    )
    unresolved = tuple(c for c in antigen_chains if c not in protein)

    antibody = heavy_atoms(target, ab_chains, amino_acids_only=True)
    if len(antibody) == 0:
        raise EmptyAntibodyAtomSet(
            f"{instance_id}: antibody chains {list(antibody_chains)} produced no "
            f"atoms in {target.entry_id}. Chains present: {sorted(protein)}. "
            f"This is the scFv domain-index trap — resolve the chain name with "
            f"sabdab.resolve_chain() before calling epitope()."
        )
    if not ag_chains:
        raise NoAntigenAtoms(
            f"{instance_id}: none of the antigen chains {list(antigen_chains)} is "
            f"a protein chain of {target.entry_id} (present: {sorted(protein)})"
        )

    tree = cKDTree(antibody.coords)
    per_chain: dict[str, tuple[ResidueKey, ...]] = {}
    union: dict[ResidueKey, None] = {}
    total_antigen_atoms = 0

    for chain_id in ag_chains:
        antigen = heavy_atoms(target, [chain_id], amino_acids_only=True)
        total_antigen_atoms += len(antigen)
        if len(antigen) == 0:
            per_chain[chain_id] = ()
            continue
        distances, _ = tree.query(
            antigen.coords, k=1, distance_upper_bound=cutoff + _KDTREE_SLACK
        )
        hits: dict[ResidueKey, None] = {}
        for index, distance in enumerate(distances):
            if np.isfinite(distance):
                hits[antigen.owners[index]] = None
        per_chain[chain_id] = tuple(sorted(hits))
        union.update(hits)

    dominant = max(per_chain, key=lambda c: len(per_chain[c])) if per_chain else None
    if dominant is not None and not per_chain[dominant]:
        dominant = None

    return EpitopeResult(
        instance_id=instance_id,
        pdb_id=target.entry_id.lower(),
        antibody_chains=ab_chains,
        antigen_chains=ag_chains,
        residues=tuple(sorted(union)),
        per_chain=per_chain,
        dominant_chain=dominant,
        cutoff=cutoff,
        n_antibody_atoms=len(antibody),
        n_antigen_atoms=total_antigen_atoms,
        unresolved_chains=unresolved,
    )


COORDINATE_RETRIES = 3
"""files.rcsb.org closes connections intermittently under sustained load.

Measured: 1 of 33 entries failed with 'Remote end closed connection without
response' and succeeded immediately on retry. Over an 8,548-entry build that
rate would drop ~260 entries, and because the driver logs and continues, the
loss would look like a property of the archive rather than of the network.
"""


def cached_structure(
    pdb_id: str,
    cache_dir: Path | str,
    timeout: float = 120.0,
    retries: int = COORDINATE_RETRIES,
) -> Target:
    """Fetch (once) and load the asymmetric unit of ``pdb_id``.

    Resumability lives here: the gzip stays on disk under ``cache_dir``, so a
    second call is a local read and an interrupted build resumes rather than
    restarting.

    The gzip is **not** decompressed to disk. gemmi reads ``.cif.gz`` directly
    through both paths ``load_target`` uses, and the decompressed copies run
    about 4x the size of the archives — 23 GB rather than 4.6 GB across the
    full protein-antigen set, measured on a 116-entry cache.

    Raises:
        CoordinateFetchError: with the id and the URL, never a bare traceback.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    short = pdb_id.lower()
    gz_path = cache_dir / f"{short}.cif.gz"
    plain_path = cache_dir / f"{short}.cif"

    if plain_path.exists():
        # An older cache kept decompressed copies; use them rather than
        # re-downloading, but never create new ones.
        return load_target(plain_path)

    if not gz_path.exists():
        gz_path.write_bytes(_download_coordinates(short, timeout, retries))
    try:
        return load_target(gz_path)
    except (OSError, EOFError, RuntimeError, ValueError) as exc:
        gz_path.unlink(missing_ok=True)
        raise CoordinateFetchError(
            f"{short.upper()} did not parse as a gzipped mmCIF ({exc}); the "
            f"cached file has been deleted so the next run re-downloads it"
        ) from exc


def _download_coordinates(short_id: str, timeout: float, retries: int) -> bytes:
    url = RCSB_COORDINATE_URL.format(pdb_id=short_id.upper())
    last: Exception | None = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            # A 404 means the entry does not exist; retrying cannot help.
            raise CoordinateFetchError(
                f"{url} returned HTTP {exc.code} for {short_id.upper()}; the "
                f"entry may be obsolete or superseded"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(2.0 * attempt)
    raise CoordinateFetchError(
        f"could not download coordinates for {short_id.upper()} from {url} "
        f"after {retries} attempts: {last}. Note the path is case-sensitive "
        f"(uppercase id) and HEAD requests are blocked — use GET."
    )


# --------------------------------------------------------------------------
# Chain resolution: summary-table chain values -> real auth chain ids.
# This lives here rather than in benchmark.sabdab because it is a question
# about the *structure* — it can only be answered with the coordinates' own
# chain ids in hand, and its failure mode (an empty antibody atom set) is
# detected by epitope() below.
# --------------------------------------------------------------------------


def resolve_chain(raw: str, available: Iterable[str]) -> str | None:
    """Map a summary-table chain value onto a real auth chain id.

    Guard 1. Rules in order, most-trusted first:

    1. exact match — covers ``AA``, ``AF``, ``LLL``, **genuine** multi-character
       auth chain ids that must not be stripped. Trying this first is not a
       nicety: 12US has chains ``7h`` *and* ``h``, so a leading-digit strip
       applied first would silently pick the wrong chain;
    2. strip a trailing domain index (``H1`` -> ``H``) — the 8.8% scFv case;
    3. strip a leading domain index (``1h`` -> ``h``) — 148 values, e.g. 12US;
    4. case-insensitive exact match, last resort, **only when the case-folded
       name is unique**. mmCIF auth chain ids are case-sensitive and the large
       capsid entries use that: 12UT carries 78 pairs differing by case alone
       (``ah``/``Ah``, ``kl``/``Kl``, ...). Folding ``AH`` there is a coin flip
       between two VP1 copies on opposite sides of the capsid, and the wrong
       one yields a complete, plausible epitope at the wrong site. When the
       fold is ambiguous this returns ``None`` rather than guessing.

    Returns:
        The auth chain id, or ``None`` when the value names no chain here.
        ``None`` is a real outcome: 1BJ1 lists antigen chain ``A``, absent from
        the coordinates. Callers log it and carry on, but must assert the
        *antibody* set is non-empty.
    """
    chains = list(available)
    if raw in chains:
        return raw
    stripped = raw.rstrip("0123456789")
    if stripped and stripped != raw and stripped in chains:
        return stripped
    stripped = raw.lstrip("0123456789")
    if stripped and stripped != raw and stripped in chains:
        return stripped
    folded = [c for c in chains if c.lower() == raw.lower()]
    if len(folded) == 1:
        return folded[0]
    return None


def resolve_chains(
    raw_values: Iterable[str], available: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Resolve several chain values at once.

    Returns:
        ``(resolved, unresolved)``. Order preserved, duplicates collapsed —
        two scFv domain indices resolve to one chain.
    """
    chains = list(available)
    resolved: list[str] = []
    unresolved: list[str] = []
    for raw in raw_values:
        hit = resolve_chain(raw, chains)
        if hit is None:
            unresolved.append(raw)
        elif hit not in resolved:
            resolved.append(hit)
    return resolved, unresolved


# --------------------------------------------------------------------------
# Guard 5: which namespace did the annotation mean?
#
# SAbDab's ``antigen_chain`` column is **not in a single namespace.** Measured
# over every entry the capped build fetched — 4,655 entries, 9,081
# protein-antigen instances — the 16,897 annotated antigen identifiers resolve
# as:
#
#  13,778  auth_asym_id, exact or domain-index — the ordinary case
#   2,041  label_asym_id of a non-polymer / branched / water asym: ions,
#          haptens, sugars, cryoprotectants. 1BJ1's ``A|V|W`` is three chains
#          against two types ``ION|PROTEIN``; 13DS's ``C|G|I|M`` is PD-L1 plus
#          three glycerols. Correctly excluded — but they are *accounted for*,
#          not unresolved
#     532  nothing, in any namespace. Always a two-letter ``A?`` id past the
#          end of the entry's asym list, i.e. SAbDab naming a chain this
#          deposition does not contain. Unaccountable, so the instance is
#          dropped rather than labelled from a partial antigen set
#     336  label_asym_id of a polypeptide that turns out to be an antibody
#          chain — this instance's own (1MHP ``C`` -> auth ``L``, the light
#          chain) or a neighbouring Fab's (1BJ1 ``B`` -> auth ``H``). Refused
#          by the antibody gate, which is the reason the gate is not optional
#     202  label_asym_id of a polypeptide: a real protein antigen chain the
#          auth-only resolver missed. 12UT annotates ``AB`` where the auth id
#          is ``0``; omitting it under-counts the epitope union
#       8  an ambiguous case fold, refused by rule 4 above
#
# Per instance that is 3.8% dropped for an unplaceable identifier and 1.0%
# whose antigen chain set an auth-only resolver got wrong.
#
# So the fix is not "switch namespace"; it is "try each namespace in a
# defensible order, record which one answered, and refuse rather than
# substitute when none does".
# --------------------------------------------------------------------------

NS_AUTH = "auth"
"""Exact match against ``_atom_site.auth_asym_id``."""

NS_AUTH_DOMAIN_INDEX = "auth_domain_index"
"""Matched after stripping an scFv domain index (``H1`` -> ``H``)."""

NS_AUTH_CASE_FOLD = "auth_case_fold"
"""Matched case-insensitively, and the fold was unique."""

NS_LABEL = "label"
"""Matched ``_pdbx_poly_seq_scheme.asym_id``; mapped to its ``pdb_strand_id``."""

NS_NON_POLYMER = "non_polymer"
"""Matched a non-polymer / branched / water asym. Accounted for, excluded."""

NS_UNRESOLVED = "unresolved"
"""Named no chain in any namespace."""

NS_CASE_AMBIGUOUS = "case_ambiguous"
"""Case fold hit more than one auth chain. Refused, never guessed."""

NS_ANTIBODY_COLLISION = "antibody_collision"
"""Resolved onto an antibody chain of this same instance. Refused."""

NAMESPACES: tuple[str, ...] = (
    NS_AUTH,
    NS_AUTH_DOMAIN_INDEX,
    NS_AUTH_CASE_FOLD,
    NS_LABEL,
    NS_NON_POLYMER,
    NS_UNRESOLVED,
    NS_CASE_AMBIGUOUS,
    NS_ANTIBODY_COLLISION,
)

USABLE_NAMESPACES: frozenset[str] = frozenset(
    {NS_AUTH, NS_AUTH_DOMAIN_INDEX, NS_AUTH_CASE_FOLD, NS_LABEL}
)
"""Outcomes that contribute a chain to the antigen atom set."""

REFUSED_NAMESPACES: frozenset[str] = frozenset(
    {NS_UNRESOLVED, NS_CASE_AMBIGUOUS}
)
"""Outcomes that mean we cannot account for the annotation at all.

An instance carrying one of these is **dropped**. It is not enough that some
*other* annotated chain resolved: an identifier we cannot place may well be a
protein antigen chain, and labelling the instance from the chains that happen
to resolve ships a silently incomplete epitope. ``non_polymer`` is not in here
because it is accounted for — we know what it is and know to exclude it.
"""


@dataclass(frozen=True)
class ChainNamespaces:
    """Every chain-identifier namespace one entry offers, read from the cif.

    Built once per entry (:func:`chain_namespaces`) and reused across the
    several antibody instances a single file can hold.
    """

    entry_id: str
    auth: tuple[str, ...]
    protein: frozenset[str]
    label_to_auth: Mapping[str, str]
    non_polymer_labels: frozenset[str]

    def case_fold_is_ambiguous(self, raw: str) -> bool:
        return sum(1 for c in self.auth if c.lower() == raw.lower()) > 1


def chain_namespaces(target: Target) -> ChainNamespaces:
    """Read the auth, label and non-polymer chain namespaces of one entry.

    ``label_to_auth`` comes from ``_pdbx_poly_seq_scheme``, which is the
    authoritative asym-to-strand mapping and covers **polymers only** — so a
    label id found here is guaranteed to name a polymer chain, and the
    non-polymer labels stay in their own set where they cannot be mistaken for
    a protein antigen. Taking the mapping from ``_atom_site`` instead would mix
    the two, because a ligand's ``auth_asym_id`` is the protein chain it sits
    on (1MHP's two Mn ions both report auth ``A``/``B``).
    """
    label_to_auth: dict[str, str] = {}
    for row in target.block.find("_pdbx_poly_seq_scheme.", ["asym_id", "pdb_strand_id"]):
        label_to_auth.setdefault(row[0], row[1])

    non_polymer: set[str] = set()
    for category, column in (
        ("_pdbx_nonpoly_scheme.", "asym_id"),
        ("_pdbx_branch_scheme.", "asym_id"),
    ):
        for row in target.block.find(category, [column]):
            non_polymer.add(row[0])

    return ChainNamespaces(
        entry_id=target.entry_id.lower(),
        auth=tuple(chain.name for chain in target.st[0]),
        protein=frozenset(protein_chain_ids(target)),
        label_to_auth=label_to_auth,
        non_polymer_labels=frozenset(non_polymer),
    )


@dataclass(frozen=True)
class ChainResolution:
    """What one annotated chain identifier turned out to be.

    ``namespace`` is one of :data:`NAMESPACES` and is carried all the way into
    the manifest, so every label in the benchmark can be traced back to the
    namespace that produced its antigen chains without re-reading any cif.
    """

    raw: str
    chain: str | None
    namespace: str

    @property
    def usable(self) -> bool:
        return self.chain is not None and self.namespace in USABLE_NAMESPACES

    @property
    def refused(self) -> bool:
        return self.namespace in REFUSED_NAMESPACES

    def __str__(self) -> str:
        if self.chain is None or self.chain == self.raw:
            return f"{self.raw}={self.namespace}"
        return f"{self.raw}->{self.chain}={self.namespace}"


def resolve_antigen_chains(
    raw_values: Iterable[str],
    namespaces: ChainNamespaces,
    antibody_chains: Iterable[str] = (),
    entry_antibody_chains: Iterable[str] = (),
) -> tuple[ChainResolution, ...]:
    """Resolve annotated antigen identifiers, recording the namespace for each.

    Rules in order. Each is tried only when the previous one misses, so the
    most trustworthy namespace always wins:

    1. exact ``auth_asym_id`` — what the column usually means;
    2. a **non-polymer** ``label_asym_id`` — an ion, hapten, sugar or
       cryoprotectant. Checked before the polymer label namespace, because the
       two overlap and a ligand identifier that happens to collide with a
       polymer asym letter must not be read as that polymer;
    3. a **polymer** ``label_asym_id``, mapped through
       ``_pdbx_poly_seq_scheme`` to its auth chain;
    4. the domain-index and unique-case-fold rules of :func:`resolve_chain`.

    Then the gate, in two parts:

    * a candidate that is an antibody chain of **this instance** is refused
      whatever namespace produced it. An instance cannot be its own antigen;
    * a candidate that is an antibody chain of **another instance in the same
      entry** (``entry_antibody_chains``: every ``Hchain``/``Lchain`` SAbDab
      declares for this PDB id) is refused *unless* it came from an exact
      ``auth`` match. 1BJ1's second Fab annotates antigen ``B|V|W``; label
      ``B`` maps to auth ``H``, which is the **first** Fab's heavy chain, so
      enabling label resolution without this half puts a neighbouring Fab into
      the antigen set. An exact auth match is still honoured, because that is
      the annotation naming a chain plainly and anti-idiotype complexes — where
      one Fab really is the other's antigen — are real.

    Nothing here ever returns a chain that was not named by one of
    ``raw_values``. There is no "pick a protein chain that is present"
    fallback, because that is how a wrong-site epitope is manufactured out of a
    bad annotation.

    Returns:
        One :class:`ChainResolution` per input value, in order. Duplicates are
        kept: two identifiers resolving to one chain is itself information.
    """
    antibody = set(antibody_chains)
    neighbours = set(entry_antibody_chains) - antibody
    auth = set(namespaces.auth)
    out: list[ChainResolution] = []

    for raw in raw_values:
        if raw in auth:
            candidate, namespace = raw, NS_AUTH
        elif raw in namespaces.non_polymer_labels:
            out.append(ChainResolution(raw, None, NS_NON_POLYMER))
            continue
        elif raw in namespaces.label_to_auth:
            candidate, namespace = namespaces.label_to_auth[raw], NS_LABEL
        else:
            fuzzy = resolve_chain(raw, namespaces.auth)
            if fuzzy is None:
                namespace = (
                    NS_CASE_AMBIGUOUS
                    if namespaces.case_fold_is_ambiguous(raw)
                    else NS_UNRESOLVED
                )
                out.append(ChainResolution(raw, None, namespace))
                continue
            candidate = fuzzy
            namespace = (
                NS_AUTH_CASE_FOLD
                if fuzzy.lower() == raw.lower()
                else NS_AUTH_DOMAIN_INDEX
            )

        if candidate in antibody or (
            namespace != NS_AUTH and candidate in neighbours
        ):
            out.append(ChainResolution(raw, candidate, NS_ANTIBODY_COLLISION))
            continue
        out.append(ChainResolution(raw, candidate, namespace))

    return tuple(out)
