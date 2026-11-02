"""Explicit-chain parsing and exact, auditable canonical residue mapping.

The automatic mapping accepts a unique exact ordered subsequence. Ambiguous
repeats require explicit canonical indices from sequence/structure metadata;
there is no silent best-alignment choice and no longest-chain fallback.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .schema import AMINO_ACIDS, ResidueID

THREE_TO_ONE = dict(
    zip(
        "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR".split(),
        "ACDEFGHIKLMNPQRSTVWY",
    )
)


@dataclass(frozen=True)
class AtomRecord:
    name: str
    element: str
    coord: tuple[float, float, float]
    occupancy: float
    altloc: str


@dataclass(frozen=True)
class MappedResidue:
    canonical_index: int
    author_id: ResidueID
    amino_acid: str
    atoms: tuple[AtomRecord, ...]


@dataclass(frozen=True)
class ChainMapping:
    sequence: str
    model_index: int
    chain_id: str
    residues: tuple[MappedResidue, ...]
    method: str

    def __post_init__(self) -> None:
        if not self.sequence or set(self.sequence) - AMINO_ACIDS:
            raise ValueError("Canonical sequence must use standard amino acids")
        ids = [r.author_id for r in self.residues]
        indices = [r.canonical_index for r in self.residues]
        if len(ids) != len(set(ids)) or len(indices) != len(set(indices)):
            raise ValueError("Mapping must be one-to-one")
        if indices != sorted(indices) or not indices:
            raise ValueError("Observed residues must have increasing canonical indices")
        for residue in self.residues:
            i = residue.canonical_index
            if type(i) is not int or not 0 <= i < len(self.sequence):
                raise ValueError("Mapped index outside canonical sequence")
            if residue.amino_acid != self.sequence[i] or residue.author_id.chain != self.chain_id:
                raise ValueError("Residue identity or chain does not match canonical mapping")
            if len({a.name for a in residue.atoms}) != len(residue.atoms):
                raise ValueError("Multiple selected atoms with the same name")
            for atom in residue.atoms:
                if len(atom.coord) != 3 or not all(math.isfinite(x) for x in atom.coord):
                    raise ValueError("Non-finite or malformed atom coordinate")

    @property
    def author_to_canonical(self) -> dict[ResidueID, int]:
        return {r.author_id: r.canonical_index for r in self.residues}

    @property
    def canonical_to_author(self) -> dict[int, ResidueID]:
        return {r.canonical_index: r.author_id for r in self.residues}

    @property
    def observed_mask(self) -> tuple[bool, ...]:
        observed = set(self.canonical_to_author)
        return tuple(i in observed for i in range(len(self.sequence)))


def unique_subsequence_mapping(sequence: str, observed: str) -> tuple[int, ...]:
    if not sequence or not observed:
        raise ValueError("Cannot map an empty sequence")
    n, m = len(sequence), len(observed)
    # Count alignments, capped at two: ambiguity is sufficient, exact count is not.
    counts = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        counts[i][m] = 1
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            counts[i][j] = min(
                2, counts[i + 1][j] + (counts[i + 1][j + 1] if sequence[i] == observed[j] else 0)
            )
    if counts[0][0] == 0:
        raise ValueError("Observed residues are not an exact subsequence; sequence/chemistry mismatch")
    if counts[0][0] != 1:
        raise ValueError("Ambiguous residue mapping; provide verified canonical indices")
    indices = []
    i = j = 0
    while j < m:
        if sequence[i] == observed[j] and counts[i + 1][j + 1]:
            indices.append(i)
            j += 1
        i += 1
    return tuple(indices)


def parse_author_selection(value: str) -> ResidueID:
    """CryptoBench author selections: A_12, A_-2, A_12B (insertion B)."""
    if not isinstance(value, str) or "_" not in value:
        raise ValueError(f"Invalid author residue selection: {value!r}")
    chain, number = value.rsplit("_", 1)
    match = re.fullmatch(r"(-?\d+)([A-Za-z]?)", number)
    if match is None:
        raise ValueError(f"Unsupported author residue identifier: {value!r}")
    return ResidueID(chain, int(match.group(1)), match.group(2))


def map_author_sites(selections: list[str], mapping: ChainMapping) -> tuple[int, ...]:
    lookup = mapping.author_to_canonical
    result = []
    for selection in selections:
        author = parse_author_selection(selection)
        if author not in lookup:
            raise ValueError(f"Annotated residue {selection} absent from selected mapped chain")
        result.append(lookup[author])
    if not result:
        raise ValueError("An annotated site cannot be empty")
    return tuple(sorted(set(result)))


def _load_model(path: str | Path, model_index: int):
    from Bio.PDB import MMCIFParser, PDBParser

    if type(model_index) is not int or model_index < 0:
        raise ValueError("Select a nonnegative zero-based model index")
    path = Path(path)
    parser = (
        MMCIFParser(QUIET=True, auth_chains=True, auth_residues=True)
        if path.suffix.lower() in {".cif", ".mmcif"}
        else PDBParser(QUIET=True, PERMISSIVE=False)
    )
    structure = parser.get_structure("input", str(path))
    models = list(structure.get_models())
    if model_index >= len(models):
        raise ValueError(f"Model index {model_index} absent from {path}")
    return models[model_index]


def mmcif_canonical_mapping(path: str | Path, *, model_index: int, chain_id: str) -> ChainMapping:
    """Use entity sequence and atom_site label_seq_id instead of guessing gaps.

    Explicitly joins author IDs to canonical indices from the SAME atom rows.
    It never zips author/label parser iterators, which can differ for ligands and
    missing residues. One selected author chain must map to one polymer entity.
    """
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    table = MMCIF2Dict(str(path))
    required = ("auth_asym_id", "auth_seq_id", "label_seq_id", "label_entity_id", "pdbx_PDB_ins_code")
    fields = {key: table.get("_atom_site." + key) for key in required}
    if any(value is None for value in fields.values()):
        raise ValueError("mmCIF lacks required author/canonical atom identity fields")
    n = len(fields["auth_asym_id"])
    if any(len(value) != n for value in fields.values()):
        raise ValueError("mmCIF atom columns have different lengths")
    model_column = table.get("_atom_site.pdbx_PDB_model_num", ["1"] * n)
    models = list(dict.fromkeys(model_column))
    if type(model_index) is not int or not 0 <= model_index < len(models):
        raise ValueError("Selected mmCIF model index absent")
    selected = [
        i
        for i in range(n)
        if fields["auth_asym_id"][i] == chain_id
        and model_column[i] == models[model_index]
        and fields["label_seq_id"][i] not in {".", "?"}
    ]
    entities = {fields["label_entity_id"][i] for i in selected}
    if len(entities) != 1:
        raise ValueError("Selected author chain does not identify exactly one polymer entity")
    entity = next(iter(entities))
    entity_ids = table.get("_entity_poly.entity_id", [])
    if entity not in entity_ids:
        raise ValueError("Canonical polymer entity sequence unavailable")
    sequence = "".join(table["_entity_poly.pdbx_seq_one_letter_code_can"][entity_ids.index(entity)].split())
    lookup = {}
    for i in selected:
        insertion = fields["pdbx_PDB_ins_code"][i]
        author = ResidueID(
            chain_id, int(fields["auth_seq_id"][i]), "" if insertion in {".", "?"} else insertion
        )
        canonical = int(fields["label_seq_id"][i]) - 1
        if author in lookup and lookup[author] != canonical:
            raise ValueError("Author residue has conflicting canonical indices")
        lookup[author] = canonical
    model = _load_model(path, model_index)
    if chain_id not in model:
        raise ValueError("Selected author chain unavailable to structure parser")
    indices = []
    for residue in model[chain_id]:
        if residue.id[0] == " ":
            author = ResidueID(chain_id, residue.id[1], residue.id[2].strip())
            if author not in lookup:
                raise ValueError("Polymer residue lacks canonical atom-site mapping")
            indices.append(lookup[author])
    mapping = read_chain(
        path, sequence=sequence, model_index=model_index, chain_id=chain_id, canonical_indices=tuple(indices)
    )
    return ChainMapping(
        mapping.sequence,
        mapping.model_index,
        mapping.chain_id,
        mapping.residues,
        "mmcif_entity_sequence_and_atom_site_label_seq_id",
    )


def _atoms_for_residue(residue) -> tuple[AtomRecord, ...]:
    if residue.is_disordered() == 2:
        raise ValueError("Ambiguous disordered residue identity; explicit normalization required")
    unpacked = residue.get_unpacked_list()
    # Choose a single residue-wide alternative, not an inconsistent atom-wise mix.
    alternatives = sorted({atom.get_altloc().strip() for atom in unpacked} - {""})
    selected_alt = (
        min(
            alternatives,
            key=lambda alt: (
                -sum(atom.get_occupancy() or 0.0 for atom in unpacked if atom.get_altloc().strip() == alt),
                alt,
            ),
        )
        if alternatives
        else ""
    )
    records = []
    for atom in unpacked:
        alt = atom.get_altloc().strip()
        if alt not in {"", selected_alt}:
            continue
        coord = tuple(float(x) for x in atom.coord)
        if not all(math.isfinite(x) for x in coord):
            raise ValueError("Non-finite atom coordinate")
        element = atom.element.strip().upper()
        if not element:
            raise ValueError("Atom element is missing")
        records.append(AtomRecord(atom.name, element, coord, float(atom.get_occupancy() or 0.0), alt))
    return tuple(sorted(records, key=lambda a: a.name))


def read_chain(
    path: str | Path,
    *,
    sequence: str,
    model_index: int,
    chain_id: str,
    canonical_indices: tuple[int, ...] | None = None,
) -> ChainMapping:
    model = _load_model(path, model_index)
    if chain_id not in model:
        raise ValueError(f"Explicit chain {chain_id!r} absent; available: {[c.id for c in model]}")
    selected = []
    for residue in model[chain_id]:
        name = residue.get_resname().upper()
        if name not in THREE_TO_ONE:
            if residue.id[0] == " " or all(atom in residue for atom in ("N", "CA", "C")):
                raise ValueError(f"Unsupported polymer chemistry: {name} {residue.id}")
            continue
        if residue.id[0] != " ":
            raise ValueError(f"Hetero polymer residue requires explicit normalization: {name}")
        author = ResidueID(chain_id, residue.id[1], residue.id[2].strip())
        selected.append((author, THREE_TO_ONE[name], _atoms_for_residue(residue)))
    observed = "".join(row[1] for row in selected)
    indices = (
        canonical_indices if canonical_indices is not None else unique_subsequence_mapping(sequence, observed)
    )
    if len(indices) != len(selected):
        raise ValueError("Explicit mapping length differs from observed chain")
    residues = tuple(MappedResidue(i, *record) for i, record in zip(indices, selected))
    return ChainMapping(
        sequence,
        model_index,
        chain_id,
        residues,
        "explicit_metadata" if canonical_indices is not None else "unique_exact_subsequence",
    )


def ligand_heavy_atoms(
    path: str | Path, *, model_index: int, residue_id: ResidueID, residue_name: str
) -> tuple[tuple[float, float, float], ...]:
    """Select ONE exact ligand instance. For evaluator/label construction only."""
    model = _load_model(path, model_index)
    if residue_id.chain not in model:
        raise ValueError("Requested ligand chain absent")
    matches = [
        r
        for r in model[residue_id.chain]
        if r.id[1] == residue_id.number
        and r.id[2].strip() == residue_id.insertion_code
        and r.resname == residue_name
        and r.id[0] != " "
    ]
    if len(matches) != 1:
        raise ValueError("Exact ligand instance is missing or ambiguous")
    coords = tuple(a.coord for a in _atoms_for_residue(matches[0]) if a.element not in {"H", "D"})
    if not coords:
        raise ValueError("Selected ligand has no heavy atoms")
    return coords


def write_normalized_pdb(mapping: ChainMapping, path: str | Path) -> dict[ResidueID, int]:
    """Stage a single chain A with canonical_index+1 numbering for fpocket.

    Returns the exact reverse map. Missing sequence residues remain numbering gaps.
    This PDB is a detector input; original author identifiers remain in mapping.
    """
    if len(mapping.sequence) > 9999:
        raise ValueError("PDB residue numbering limit exceeded")
    inverse = {value: key for key, value in THREE_TO_ONE.items()}
    lines = []
    lookup = {}
    serial = 1
    for residue in mapping.residues:
        number = residue.canonical_index + 1
        lookup[ResidueID("A", number)] = residue.canonical_index
        for atom in residue.atoms:
            if atom.element in {"H", "D"}:
                continue
            x, y, z = atom.coord
            if any(v < -999.999 or v > 9999.999 for v in (x, y, z)) or serial > 99999:
                raise ValueError("PDB coordinate/serial field capacity exceeded")
            atom_name = f" {atom.name:<3}" if len(atom.name) < 4 else atom.name
            lines.append(
                f"ATOM  {serial:5d} {atom_name:4s} {inverse[residue.amino_acid]:3s} A{number:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {atom.element:>2s}"
            )
            serial += 1
    if not lines:
        raise ValueError("No atoms available to stage")
    Path(path).write_text("\n".join(lines) + "\nTER\nEND\n")
    return lookup
