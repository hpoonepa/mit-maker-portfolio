# SPDX-License-Identifier: MIT
"""Shared fixtures.

The synthetic structures are built with gemmi and written through its own mmCIF
writer, rather than hand-authored as text, so the fixtures exercise the same
parse path as real files.

Author numbering is deliberately label_seq_id + 100. Any code that confuses the
two schemes fails loudly here instead of passing by coincidence, which is what
would happen with a fixture whose author numbers start at 1.
"""

from pathlib import Path

import gemmi
import pytest

# label_seq -> author number is +100. Atoms exist for label_seq 1, 2, 3, 6.
# Label 4 and 5 (author 104, 105) are declared but unmodelled - the same shape
# of gap as 6F5J chain C residues 399-416.
_MODELLED = [(1, 101, "GLY"), (2, 102, "ALA"), (3, 103, "VAL"), (6, 106, "PHE")]
_FULL_SEQUENCE = ["GLY", "ALA", "VAL", "LEU", "ILE", "PHE"]

# Appended by hand because gemmi does not write this category. It is optional in
# mmCIF and absent from many real entries, which is the whole point of having a
# fixture both with and without it.
_UNOBS_LOOP = """#
loop_
_pdbx_unobs_or_zero_occ_residues.id
_pdbx_unobs_or_zero_occ_residues.PDB_model_num
_pdbx_unobs_or_zero_occ_residues.polymer_flag
_pdbx_unobs_or_zero_occ_residues.occupancy_flag
_pdbx_unobs_or_zero_occ_residues.auth_asym_id
_pdbx_unobs_or_zero_occ_residues.auth_comp_id
_pdbx_unobs_or_zero_occ_residues.auth_seq_id
_pdbx_unobs_or_zero_occ_residues.PDB_ins_code
1 1 Y 1 A LEU 104 ?
2 1 Y 1 A ILE 105 ?
#
"""


def _write_synthetic(
    path: Path,
    include_unobs: bool,
    occupancies: dict[int, float] | None = None,
) -> Path:
    occupancies = occupancies or {}
    st = gemmi.Structure()
    st.name = "TEST"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")

    for label_seq, auth_seq, comp in _MODELLED:
        res = gemmi.Residue()
        res.name = comp
        res.seqid = gemmi.SeqId(auth_seq, " ")
        res.label_seq = label_seq
        res.het_flag = "A"
        res.entity_type = gemmi.EntityType.Polymer
        occ = occupancies.get(auth_seq, 1.0)
        # Three backbone atoms, spaced so SASA is non-degenerate.
        for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5), ("C", "C", 3.0)):
            atom = gemmi.Atom()
            atom.name = name
            atom.element = gemmi.Element(elem)
            atom.pos = gemmi.Position(label_seq * 6.0 + dx, 0.0, 0.0)
            atom.occ = occ
            atom.b_iso = 20.0
            res.add_atom(atom)
        chain.add_residue(res)

    model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()

    # Declare more residues than were modelled. Must be set AFTER
    # setup_entities(), which rebuilds the entity list.
    for entity in st.entities:
        if entity.entity_type == gemmi.EntityType.Polymer:
            entity.full_sequence = list(_FULL_SEQUENCE)

    doc = st.make_mmcif_document()
    text = doc.as_string()
    if include_unobs:
        text += _UNOBS_LOOP
    path.write_text(text)
    return path


@pytest.fixture
def cif_with_unobs_category(tmp_path: Path) -> Path:
    """Entry that declares its own unmodelled residues, as curated ones do."""
    return _write_synthetic(tmp_path / "with_unobs.cif", include_unobs=True)


@pytest.fixture
def cif_without_unobs_category(tmp_path: Path) -> Path:
    """Same gap, no _pdbx_unobs category.

    Code that trusts that category alone reports 'nothing missing' here, which
    is the bug this fixture exists to catch.
    """
    return _write_synthetic(tmp_path / "without_unobs.cif", include_unobs=False)


@pytest.fixture
def cif_with_zero_occupancy(tmp_path: Path) -> Path:
    """Residue 103 present in ATOM records but modelled at zero occupancy."""
    return _write_synthetic(
        tmp_path / "zero_occ.cif", include_unobs=False, occupancies={103: 0.0}
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / ".cache"


@pytest.fixture(scope="session")
def real_6f5j() -> Path:
    """The deformed wing virus capsid entry that motivated this project.

    Downloaded once into .cache/ and reused. Skipped rather than failed when
    offline, so the deterministic suite still runs without a network.
    """
    import urllib.error
    import urllib.request

    CACHE.mkdir(exist_ok=True)
    path = CACHE / "6f5j_updated.cif"
    if not path.exists():  # pragma: no cover - network path
        url = "https://www.ebi.ac.uk/pdbe/entry-files/download/6f5j_updated.cif"
        try:
            # An unavailable public endpoint must not hang the entire suite or
            # leave a partial coordinate file that a later run would trust.
            with urllib.request.urlopen(url, timeout=30) as response:
                coordinates = response.read()
            partial = path.with_suffix(".cif.partial")
            partial.write_bytes(coordinates)
            partial.replace(path)
        except (urllib.error.URLError, OSError) as exc:
            pytest.skip(f"cannot download 6F5J: {exc}")
    return path


@pytest.fixture
def two_chain_structure():
    """Two protein chains 60 A apart — well beyond any neighbourhood cutoff.

    Deliberately NOT in contact: the point of the multi-focus trim is the chain
    that proximity would discard, so a fixture whose chains touch would pass
    against the broken implementation too.
    """
    st = gemmi.Structure()
    st.name = "TWOCHAIN"
    model = gemmi.Model("1")
    for chain_name, x0 in (("A", 0.0), ("Z", 60.0)):
        chain = gemmi.Chain(chain_name)
        for i in range(1, 4):
            res = gemmi.Residue()
            res.name = "ALA"
            res.seqid = gemmi.SeqId(i, " ")
            res.label_seq = i
            res.het_flag = "A"
            res.entity_type = gemmi.EntityType.Polymer
            for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5), ("C", "C", 3.0)):
                atom = gemmi.Atom()
                atom.name = name
                atom.element = gemmi.Element(elem)
                atom.pos = gemmi.Position(x0 + i * 4.0 + dx, 0.0, 0.0)
                atom.occ = 1.0
                atom.b_iso = 20.0
                res.add_atom(atom)
            chain.add_residue(res)
        model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    return st
