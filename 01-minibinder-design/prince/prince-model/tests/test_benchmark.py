# SPDX-License-Identifier: MIT
"""Tests for the epitope benchmark pipeline.

The tests that matter most here are the four guard regressions and the three
validation targets. Each guard is a bug that produced *plausible* wrong labels —
an empty epitope, an epitope at the wrong site, a lattice contact, an inflated
N — so none of them would have been caught by a test that merely checked the
pipeline ran.

Network-dependent tests are marked ``network`` and skip when the cache is cold
and the machine is offline, so the deterministic suite still runs unplugged.
"""

from __future__ import annotations

import gzip
import inspect
import json
from pathlib import Path

import gemmi
import numpy as np
import pytest

from benchmark import cluster as clusterlib
from benchmark import epitope as epitopelib
from benchmark import manifest as manifestlib
from benchmark import sabdab
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import load_target

REPO_ROOT = Path(__file__).resolve().parents[1]
CIF_CACHE = REPO_ROOT / ".cache" / "benchmark" / "cif"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def snapshot() -> sabdab.Snapshot:
    """The pinned SAbDab snapshot. Never fetched during a test run."""
    try:
        return sabdab.load_snapshot()
    except sabdab.SabdabError as exc:  # pragma: no cover - repo misconfiguration
        pytest.skip(f"no pinned snapshot: {exc}")


@pytest.fixture(scope="session")
def instances(snapshot: sabdab.Snapshot) -> list[sabdab.AntibodyInstance]:
    return sabdab.parse_instances(snapshot.csv_text)


def _structure(pdb_id: str):
    """Load a cached entry, downloading once if the cache is cold."""
    try:
        return epitopelib.cached_structure(pdb_id, CIF_CACHE)
    except epitopelib.CoordinateFetchError as exc:  # pragma: no cover - offline
        pytest.skip(f"cannot obtain {pdb_id}: {exc}")


def _epitope_for(pdb_id: str, instance_id: str, instances):
    """Run the full resolution + epitope path for one named instance."""
    target = _structure(pdb_id)
    chains = [chain.name for chain in target.st[0]]
    inst = next(i for i in instances if i.instance_id == instance_id)
    antibody, _ = epitopelib.resolve_chains(inst.antibody_chains, chains)
    antigen, _ = epitopelib.resolve_chains(inst.antigen_chains, chains)
    return epitopelib.epitope(
        target,
        instance_id=inst.instance_id,
        antibody_chains=antibody,
        antigen_chains=antigen,
    )


def _two_chain_structure(tmp_path: Path, separation: float, n_antigen: int = 8) -> Path:
    """A minimal two-chain complex: chain H the antibody, chain G the antigen.

    Residues are single CA atoms 8 A apart along x, with chain G offset in y by
    ``separation``, so the number of contacts is set by geometry alone and the
    expected answer is arithmetic rather than a magic number.
    """
    st = gemmi.Structure()
    st.name = "SYNTH"
    model = gemmi.Model("1")

    def add_chain(name: str, count: int, y: float, first_seq: int = 1) -> None:
        chain = gemmi.Chain(name)
        for index in range(count):
            residue = gemmi.Residue()
            residue.name = "ALA"
            residue.seqid = gemmi.SeqId(first_seq + index, " ")
            residue.label_seq = index + 1
            residue.het_flag = "A"
            residue.entity_type = gemmi.EntityType.Polymer
            atom = gemmi.Atom()
            atom.name = "CA"
            atom.element = gemmi.Element("C")
            atom.pos = gemmi.Position(index * 8.0, y, 0.0)
            atom.occ = 1.0
            atom.b_iso = 20.0
            residue.add_atom(atom)
            chain.add_residue(residue)
        model.add_chain(chain)

    add_chain("H", 12, 0.0)
    add_chain("G", n_antigen, separation, first_seq = 101)
    st.add_model(model)
    st.setup_entities()
    path = tmp_path / f"synth_{separation:.1f}_{n_antigen}.cif"
    path.write_text(st.make_mmcif_document().as_string())
    return path


# --------------------------------------------------------------------------
# the cKDTree-not-NeighborSearch choice
# --------------------------------------------------------------------------


def test_epitope_uses_ckdtree_not_gemmi_neighborsearch():
    """Pin the search implementation.

    ``gemmi.NeighborSearch`` applies crystal symmetry by default, so a lattice
    mate of the antibody would be reported as contacting the antigen and
    residues on the far side of the antigen would enter the label silently.
    This test fails if someone swaps the implementation back.
    """
    source = inspect.getsource(epitopelib.epitope)
    assert "cKDTree" in source
    assert "NeighborSearch" not in source
    # The name appears in this module's docstring, explaining why it is not
    # used; what must never appear is a call to it.
    module_source = inspect.getsource(epitopelib)
    assert "NeighborSearch(" not in module_source
    assert "gemmi.NeighborSearch" not in module_source.replace(
        "``gemmi.NeighborSearch``", ""
    )


def test_ckdtree_ignores_periodicity(tmp_path: Path):
    """A neighbour search with no unit cell cannot find a symmetry mate.

    Two chains 30 A apart in a 40 A cell are lattice neighbours under symmetry
    and non-neighbours without it. cKDTree must report zero contacts.
    """
    path = _two_chain_structure(tmp_path, separation=30.0)
    target = load_target(path)
    target.st.cell = gemmi.UnitCell(40.0, 40.0, 40.0, 90.0, 90.0, 90.0)
    target.st.spacegroup_hm = "P 1"
    result = epitopelib.epitope(target, "synth", ["H"], ["G"])
    assert result.size == 0


# --------------------------------------------------------------------------
# the definition: cutoff, hydrogens, occupancy, amino acids
# --------------------------------------------------------------------------


def test_cutoff_constants_are_the_published_conventions():
    assert epitopelib.EPITOPE_CUTOFF_A == 4.5
    assert epitopelib.SENSITIVITY_CUTOFF_A == 4.0
    assert epitopelib.MIN_EPITOPE_RESIDUES == 5


def test_cutoff_boundary_is_inclusive(tmp_path: Path):
    """A contact at exactly the cutoff counts; one just beyond does not."""
    inside = load_target(_two_chain_structure(tmp_path, separation=4.5))
    outside = load_target(_two_chain_structure(tmp_path, separation=4.6))
    assert epitopelib.epitope(inside, "s", ["H"], ["G"]).size == 8
    assert epitopelib.epitope(outside, "s", ["H"], ["G"]).size == 0


def test_sensitivity_cutoff_is_a_subset_of_the_primary(tmp_path: Path):
    target = load_target(_two_chain_structure(tmp_path, separation=4.2))
    primary = epitopelib.epitope(
        target, "s", ["H"], ["G"], cutoff=epitopelib.EPITOPE_CUTOFF_A
    )
    strict = epitopelib.epitope(
        target, "s", ["H"], ["G"], cutoff=epitopelib.SENSITIVITY_CUTOFF_A
    )
    assert set(strict.residues) <= set(primary.residues)
    assert strict.size == 0 and primary.size == 8


def test_heavy_atoms_excludes_hydrogens_and_zero_occupancy(tmp_path: Path):
    """Contact labels use occupied heavy atoms."""
    st = gemmi.Structure()
    st.name = "OCC"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    residue = gemmi.Residue()
    residue.name = "ALA"
    residue.seqid = gemmi.SeqId(1, " ")
    residue.label_seq = 1
    residue.het_flag = "A"
    residue.entity_type = gemmi.EntityType.Polymer
    for name, element, occ in (("CA", "C", 1.0), ("CB", "C", 0.0), ("HA", "H", 1.0)):
        atom = gemmi.Atom()
        atom.name = name
        atom.element = gemmi.Element(element)
        atom.pos = gemmi.Position(0.0, 0.0, 0.0)
        atom.occ = occ
        residue.add_atom(atom)
    chain.add_residue(residue)
    model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    path = tmp_path / "occ.cif"
    path.write_text(st.make_mmcif_document().as_string())

    atoms = epitopelib.heavy_atoms(load_target(path), ["A"])
    assert len(atoms) == 1


def test_antibody_atom_set_is_restricted_to_amino_acids():
    """The AsEP/PECAN convention: antibody atoms are protein atoms only.

    1BJ1 carries ions and waters; the antibody atom count must not include
    them, and the modified-residue table must count pyroglutamate and friends
    as protein (6AL0 chain L begins with PCA).
    """
    target = _structure("1bj1")
    protein_only = epitopelib.heavy_atoms(target, ["H", "L"], amino_acids_only=True)
    everything = epitopelib.heavy_atoms(target, ["H", "L"], amino_acids_only=False)
    assert 0 < len(protein_only) < len(everything)


# --------------------------------------------------------------------------
# guard 1 — scFv chain naming
# --------------------------------------------------------------------------


def test_guard1_resolve_chain_strips_trailing_domain_index():
    """``Hchain='H1'`` on a structure whose chain is ``H``."""
    assert epitopelib.resolve_chain("H1", ["H", "L", "A"]) == "H"
    assert epitopelib.resolve_chain("H2", ["H", "L", "A"]) == "H"


def test_guard1_resolve_chain_strips_leading_domain_index():
    """148 values put the index first, e.g. 12US writes ``1h``/``1l``."""
    assert epitopelib.resolve_chain("1h", ["h", "l"]) == "h"
    assert epitopelib.resolve_chain("2l", ["h", "l"]) == "l"


def test_guard1_resolve_chain_never_strips_a_genuine_multichar_chain():
    """The correction to naive suffix-stripping.

    This table contains real multi-character auth chain ids — ``AA``, ``AF``,
    ``LLL``, ``PPP`` — and 7PA6 writes an scFv as ``PPP2``/``PPP1`` on chain
    ``PPP``. A blind regex strip would turn ``AF`` into ``A`` and silently use
    the wrong chain, so exact matching must be tried first.
    """
    assert epitopelib.resolve_chain("AF", ["A", "AF", "F"]) == "AF"
    assert epitopelib.resolve_chain("LLL", ["LLL", "L"]) == "LLL"
    assert epitopelib.resolve_chain("PPP2", ["PPP", "FFF", "JJJ"]) == "PPP"
    assert epitopelib.resolve_chain("A1", ["A1", "A"]) == "A1"


def test_guard1_resolve_chain_returns_none_for_absent_chain():
    """1BJ1 lists antigen chain 'A', which is not in the coordinates."""
    assert epitopelib.resolve_chain("Z", ["A", "B"]) is None


def test_guard1_empty_antibody_atom_set_raises(tmp_path: Path):
    """The assertion itself. An empty antibody set must never be an empty label.

    Without this, an unresolved scFv name yields size 0, which the size floor
    then discards as 'a tiny interface' — the bug hides inside a legitimate
    filter.
    """
    target = load_target(_two_chain_structure(tmp_path, separation=4.0))
    with pytest.raises(epitopelib.EmptyAntibodyAtomSet) as excinfo:
        epitopelib.epitope(target, "synth", ["H1"], ["G"])
    assert "H1" in str(excinfo.value)
    assert "resolve_chain" in str(excinfo.value)


def test_guard1_suffixed_values_are_88_percent_absent_but_present(instances):
    """The population fact that makes guard 1 necessary, measured on the pin."""
    values = [
        chain
        for inst in instances
        for chain in inst.antibody_chains
    ]
    suffixed = [
        v for v in values if len(v) > 1 and (v[-1].isdigit() or v[0].isdigit())
    ]
    fraction = len(suffixed) / len(values)
    assert 0.07 < fraction < 0.11, f"{len(suffixed)}/{len(values)} = {fraction:.3f}"


@pytest.mark.network
def test_guard1_real_scfv_resolves_and_yields_an_epitope(instances):
    """7PA6: scFv ``PPP2``/``PPP1`` on chain ``PPP``, antigens ``FFF``/``JJJ``."""
    result = _epitope_for("7pa6", "pdb_00007pa6-PPP2-PPP1", instances)
    assert result.antibody_chains == ("PPP",)
    assert result.n_antibody_atoms > 0
    assert result.size >= epitopelib.MIN_EPITOPE_RESIDUES


# --------------------------------------------------------------------------
# guard 2 — antigen chain selection
# --------------------------------------------------------------------------


def test_guard2_antigen_chain_field_is_pipe_delimited():
    assert sabdab.split_tokens("A|V|W") == ("A", "V", "W")
    assert sabdab.split_tokens("ION|PROTEIN") == ("ION", "PROTEIN")
    assert sabdab.split_tokens("NA") == ()
    assert sabdab.split_tokens("") == ()


def test_guard2_antigen_chain_and_type_are_not_positionally_aligned(instances):
    """Why chain typing is done from coordinates, not from ``antigen_type``.

    1BJ1 lists three antigen chains against two types, so ``zip`` would label
    chain V as PROTEIN and chain W as nothing — or worse, the other way round.
    """
    inst = next(i for i in instances if i.instance_id == "pdb_00001bj1-H-L")
    assert len(inst.antigen_chains) == 3
    assert inst.antigen_types == frozenset({"ION", "PROTEIN"})
    assert len(inst.antigen_chains) != len(inst.antigen_types)


@pytest.mark.network
def test_guard2_wrong_single_antigen_chain_gives_a_wrong_site():
    """The trap, reproduced: 1BJ1 chain V alone is a 2-residue wrong-site hit."""
    target = _structure("1bj1")
    only_v = epitopelib.epitope(target, "1bj1", ["H", "L"], ["V"])
    only_w = epitopelib.epitope(target, "1bj1", ["H", "L"], ["W"])
    assert only_v.size == 2
    assert only_w.size == 17


@pytest.mark.network
def test_guard2_union_over_protein_antigen_chains(instances):
    """The fix: union the contacts rather than guessing at one chain."""
    result = _epitope_for("1bj1", "pdb_00001bj1-H-L", instances)
    assert result.antigen_chains == ("V", "W")
    assert result.size == 19
    assert set(result.per_chain) == {"V", "W"}
    assert len(result.per_chain["V"]) == 2
    assert len(result.per_chain["W"]) == 17
    assert result.dominant_chain == "W"


@pytest.mark.network
def test_guard2_non_protein_antigen_chains_are_excluded(instances):
    """1BJ1's declared antigen chain 'A' is an ion and is not in the label."""
    result = _epitope_for("1bj1", "pdb_00001bj1-H-L", instances)
    assert "A" not in result.antigen_chains
    assert "A" in result.unresolved_chains or "A" not in result.per_chain


def test_guard2_protein_chain_ids_types_from_coordinates(tmp_path: Path):
    target = load_target(_two_chain_structure(tmp_path, separation=4.0))
    assert epitopelib.protein_chain_ids(target) == {"H", "G"}


# --------------------------------------------------------------------------
# guard 3 — minimum epitope size, and nothing dropped silently
# --------------------------------------------------------------------------


def test_guard3_size_floor_flags_a_small_interface(tmp_path: Path):
    """Three contacts is a packing artefact, not an interface."""
    target = load_target(_two_chain_structure(tmp_path, separation=4.0, n_antigen=3))
    result = epitopelib.epitope(target, "synth", ["H"], ["G"])
    assert result.size == 3
    assert not result.passes_size_floor


def test_guard3_size_floor_passes_at_exactly_five(tmp_path: Path):
    target = load_target(_two_chain_structure(tmp_path, separation=4.0, n_antigen=5))
    result = epitopelib.epitope(target, "synth", ["H"], ["G"])
    assert result.size == 5
    assert result.passes_size_floor


def test_guard3_dropped_rows_are_written_with_a_reason(tmp_path: Path):
    """Every drop is a row in dropped.csv with a groupable reason string."""
    path = manifestlib.write_dropped(
        [
            manifestlib.DroppedRow("x-H-L", "6al0", "below_size_floor", "2 < 5"),
            manifestlib.DroppedRow("y-H-L", "1abc", "empty_antibody_atom_set", ""),
        ],
        tmp_path / "dropped.csv",
    )
    text = path.read_text()
    assert "below_size_floor" in text
    assert "empty_antibody_atom_set" in text
    assert text.splitlines()[0] == "instance_id,pdb_id,reason,detail"


# --------------------------------------------------------------------------
# guard 4 — one row per antibody instance, not per structure
# --------------------------------------------------------------------------


def test_guard4_rows_instances_and_entries_are_three_numbers(instances, snapshot):
    """Counting rows as structures inflates N by 1.93x on the pinned snapshot."""
    counts = sabdab.count_instances(instances, n_rows=snapshot.n_rows)
    assert counts.n_rows == 22548
    assert counts.n_instances == 22548
    assert counts.n_entries == 11667
    assert 1.9 < counts.row_inflation < 2.0


def test_guard4_protein_antigen_population_matches_the_spec(instances):
    """16,800 protein-antigen instances across 8,548 entries, measured."""
    protein = [i for i in instances if i.has_protein_antigen]
    assert len(protein) == 16800
    assert len({i.pdb_id for i in protein}) == 8548


def test_guard4_multiple_instances_per_entry_are_kept_apart(instances):
    """1BJ1 holds two Fabs; each is its own row with its own epitope."""
    ours = [i for i in instances if i.pdb_id == "1bj1"]
    assert len(ours) == 2
    assert {i.instance_id for i in ours} == {
        "pdb_00001bj1-H-L",
        "pdb_00001bj1-K-J",
    }


def test_guard4_antigen_chains_are_unioned_across_rows_of_one_instance():
    """Defence against a future table that emits one row per antigen chain."""
    csv_text = (
        "INSTANCE,PDB,Hchain,Lchain,antigen_chain,antigen_type,method,resolution\n"
        "i1,pdb_00001abc,H,L,V,PROTEIN,XRAY,2.0\n"
        "i1,pdb_00001abc,H,L,W,PROTEIN,XRAY,2.0\n"
    )
    parsed = sabdab.parse_instances(csv_text)
    assert len(parsed) == 1
    assert parsed[0].antigen_chains == ("V", "W")


# --------------------------------------------------------------------------
# guard 5 — which namespace did SAbDab's chain id mean?
#
# The bug these pin: the resolver only looked in ``auth_asym_id``, so 41.5% of
# instances logged an unresolved antigen chain. Three different things were
# hiding under that one note, and only the middle one was a wrong label.
# --------------------------------------------------------------------------


def _labelled_structure(tmp_path: Path) -> Path:
    """A three-chain complex whose label and auth namespaces disagree.

    Modelled on 1MHP, where ``label_asym_id`` ``C`` is auth chain ``L`` — the
    Fab's own light chain — while SAbDab annotates the antigen as ``C``.
    Auth ``H``/``L`` are the antibody, auth ``A`` the antigen; in label space
    they are ``B``/``C``/``A``. So label ``C`` is a trap and label ``A`` is not.
    """
    st = gemmi.Structure()
    st.name = "LBL"
    model = gemmi.Model("1")
    for name, y, first in (("H", 0.0, 1), ("L", 20.0, 1), ("A", 4.0, 101)):
        chain = gemmi.Chain(name)
        for index in range(8):
            residue = gemmi.Residue()
            residue.name = "ALA"
            residue.seqid = gemmi.SeqId(first + index, " ")
            residue.label_seq = index + 1
            residue.het_flag = "A"
            residue.entity_type = gemmi.EntityType.Polymer
            atom = gemmi.Atom()
            atom.name = "CA"
            atom.element = gemmi.Element("C")
            atom.pos = gemmi.Position(index * 8.0, y, 0.0)
            atom.occ = 1.0
            atom.b_iso = 20.0
            residue.add_atom(atom)
            chain.add_residue(residue)
        model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    text = st.make_mmcif_document().as_string()
    # gemmi writes no poly_seq_scheme for a structure built in memory; append
    # the auth/label mapping by hand, which is the whole point of the fixture.
    text += (
        "loop_\n"
        "_pdbx_poly_seq_scheme.asym_id\n"
        "_pdbx_poly_seq_scheme.pdb_strand_id\n"
        "A A\n"
        "B H\n"
        "C L\n"
        "loop_\n"
        "_pdbx_nonpoly_scheme.asym_id\n"
        "_pdbx_nonpoly_scheme.pdb_strand_id\n"
        "D A\n"
    )
    path = tmp_path / "labelled.cif"
    path.write_text(text)
    return path


def test_guard5_label_namespace_is_read_from_the_cif(tmp_path: Path):
    spaces = epitopelib.chain_namespaces(load_target(_labelled_structure(tmp_path)))
    assert spaces.auth == ("H", "L", "A")
    assert spaces.protein == {"H", "L", "A"}
    assert dict(spaces.label_to_auth) == {"A": "A", "B": "H", "C": "L"}
    assert spaces.non_polymer_labels == frozenset({"D"})


def test_guard5_a_label_id_resolves_to_its_auth_chain(tmp_path: Path):
    """The 134 missed protein antigen chains: label ``B`` is auth ``H``."""
    spaces = epitopelib.chain_namespaces(load_target(_labelled_structure(tmp_path)))
    (res,) = epitopelib.resolve_antigen_chains(["B"], spaces)
    assert (res.chain, res.namespace) == ("H", epitopelib.NS_LABEL)
    assert res.usable


def test_guard5_an_antigen_that_is_an_antibody_chain_is_refused(tmp_path: Path):
    """The 1MHP trap: label ``C`` is the Fab's light chain, not the antigen.

    The resolver must refuse it rather than hand it to :func:`epitope`, and the
    instance must still be labelled from the antigen chain that did resolve.
    """
    spaces = epitopelib.chain_namespaces(load_target(_labelled_structure(tmp_path)))
    resolutions = epitopelib.resolve_antigen_chains(
        ["A", "C"], spaces, antibody_chains=["H", "L"]
    )
    by_raw = {r.raw: r for r in resolutions}
    assert by_raw["A"].namespace == epitopelib.NS_AUTH
    assert by_raw["A"].usable
    assert by_raw["C"].namespace == epitopelib.NS_ANTIBODY_COLLISION
    assert by_raw["C"].chain == "L"
    assert not by_raw["C"].usable
    # refused, not unresolvable: the instance is still labelled, from "A"
    assert not by_raw["C"].refused
    assert [r.chain for r in resolutions if r.usable] == ["A"]


def test_guard5_epitope_fails_loudly_on_an_antibody_antigen_chain(tmp_path: Path):
    """The gate that would have caught this, at the point of no return.

    Guard 2's union rule used to filter the overlap out silently, so a caller
    that bypassed the resolver got either a confident wrong label or a
    ``NoAntigenAtoms`` that blamed the structure.
    """
    target = load_target(_labelled_structure(tmp_path))
    with pytest.raises(epitopelib.AntigenIsAntibodyChain) as excinfo:
        epitopelib.epitope(target, "synth", ["H", "L"], ["A", "L"])
    assert "'L'" in str(excinfo.value)
    assert "resolve_antigen_chains" in str(excinfo.value)


def test_guard5_unresolvable_chain_is_refused_not_substituted(tmp_path: Path):
    """The whole point: no "some protein chain that is present" fallback.

    ``ZZ`` names nothing in any namespace, so it is refused by name. The
    resolver must not quietly offer auth ``A`` in its place just because ``A``
    is a protein chain that happens to be there.
    """
    spaces = epitopelib.chain_namespaces(load_target(_labelled_structure(tmp_path)))
    (res,) = epitopelib.resolve_antigen_chains(["ZZ"], spaces)
    assert res.chain is None
    assert res.namespace == epitopelib.NS_UNRESOLVED
    assert res.refused
    assert not res.usable


def test_guard5_ambiguous_case_fold_is_refused():
    """The wrong-molecule bug. 12UT carries 78 auth pairs differing by case.

    Folding ``AH`` against a chain list holding both ``ah`` and ``Ah`` is a
    coin flip between two VP1 copies on opposite sides of a capsid, and the
    wrong one yields a complete, plausible epitope at the wrong site. A unique
    fold is still allowed, because that is a real naming convention.
    """
    assert epitopelib.resolve_chain("AH", ["ah", "Ah", "z"]) is None
    assert epitopelib.resolve_chain("AH", ["ah", "z"]) == "ah"


def test_guard5_namespace_round_trips_through_the_manifest():
    """The namespace that matched has to survive into the shipped file."""
    text = manifestlib.format_chain_resolution(
        [
            epitopelib.ChainResolution("A", "L", epitopelib.NS_ANTIBODY_COLLISION),
            epitopelib.ChainResolution("V", "V", epitopelib.NS_AUTH),
            epitopelib.ChainResolution("AB", "0", epitopelib.NS_LABEL),
        ]
    )
    assert text == "A->L=antibody_collision|V=auth|AB->0=label"
    row = manifestlib.ManifestRow(
        instance_id="i", pdb_id="1abc", heavy_chain="H", light_chain="L",
        antigen_chains="V|0", epitope_residues="V:1", n_epitope=1,
        dominant_chain="V", n_epitope_dominant=1, cluster_id="c", split="train",
        cutoff_angstrom=4.5, method="XRAY", resolution="2.00",
        chain_resolution=text,
    )
    assert row.resolution_namespaces == ("antibody_collision", "auth", "label")
    assert "chain_resolution" in manifestlib.MANIFEST_COLUMNS


@pytest.mark.network
def test_guard5_1mhp_antigen_c_is_the_light_chain_in_label_space(instances):
    """The real entry the 41.5% note was read off, resolved case by case.

    1MHP annotates antigen ``A|C`` with types ``PROTEIN|ION``. ``A`` is the
    integrin. ``C`` is *not* the Mn ion's asym (that is ``G``) — it is the
    ``label_asym_id`` of auth chain ``L``, the Fab light chain. Resolving ``C``
    in label space without the antibody gate would measure the epitope against
    the antibody itself.
    """
    target = _structure("1mhp")
    spaces = epitopelib.chain_namespaces(target)
    assert spaces.label_to_auth["C"] == "L"
    assert spaces.label_to_auth["A"] == "A"

    inst = next(i for i in instances if i.instance_id == "pdb_00001mhp-H-L")
    assert inst.antigen_chains == ("A", "C")
    antibody, _ = epitopelib.resolve_chains(inst.antibody_chains, list(spaces.auth))
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains, spaces, antibody_chains=antibody
    )
    assert [(r.raw, r.chain, r.namespace) for r in resolutions] == [
        ("A", "A", epitopelib.NS_AUTH),
        ("C", "L", epitopelib.NS_ANTIBODY_COLLISION),
    ]
    assert [r.chain for r in resolutions if r.usable] == ["A"]
    assert not any(r.refused for r in resolutions)


@pytest.mark.network
def test_guard5_1bj1_ion_chain_a_never_enters_the_antigen_set(instances):
    """The validation entry the lead flagged. It was never substituted.

    1BJ1's note read ``antigen chain(s) ['A'] not in coordinates; using
    ['V', 'W']`` — but ``V`` and ``W`` *are* two of the three annotated antigen
    chains, so nothing was substituted and the 17-residue label was right.
    ``A`` is SAbDab's identifier for the sulfate ion; in this file it is the
    ``label_asym_id`` of auth ``L``, the light chain, so it is refused by the
    gate rather than used.
    """
    target = _structure("1bj1")
    spaces = epitopelib.chain_namespaces(target)
    inst = next(i for i in instances if i.instance_id == "pdb_00001bj1-H-L")
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains, spaces, antibody_chains=["H", "L"]
    )
    usable = [r.chain for r in resolutions if r.usable]
    assert usable == ["V", "W"]
    assert not any(r.refused for r in resolutions)
    assert "L" not in usable and "H" not in usable


@pytest.mark.network
def test_guard5_1bj1_second_fab_does_not_eat_the_first_fabs_heavy_chain(instances):
    """The regression that enabling label resolution introduces if unguarded.

    1BJ1 holds two Fabs. The second (``K-J``) annotates antigen ``B|V|W``, and
    label ``B`` is auth ``H`` — the *first* Fab's heavy chain. Resolving it puts
    a neighbouring antibody into the antigen set, which is wrong even though
    the epitope union happens to come out the same size.
    """
    target = _structure("1bj1")
    spaces = epitopelib.chain_namespaces(target)
    assert spaces.label_to_auth["B"] == "H"

    inst = next(i for i in instances if i.instance_id == "pdb_00001bj1-K-J")
    assert inst.antigen_chains == ("B", "V", "W")
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains,
        spaces,
        antibody_chains=["K", "J"],
        entry_antibody_chains=["H", "L", "K", "J"],
    )
    by_raw = {r.raw: r for r in resolutions}
    assert by_raw["B"].chain == "H"
    assert by_raw["B"].namespace == epitopelib.NS_ANTIBODY_COLLISION
    assert [r.chain for r in resolutions if r.usable] == ["V", "W"]


def test_guard5_an_exact_auth_match_on_another_fab_is_still_honoured(tmp_path: Path):
    """The exception: anti-idiotype complexes, where a Fab is the antigen.

    The sibling gate only distrusts an *indirect* resolution. When SAbDab names
    a neighbouring antibody chain in auth space it is saying what it means, and
    refusing that would silently drop every anti-idiotype entry.
    """
    spaces = epitopelib.chain_namespaces(load_target(_labelled_structure(tmp_path)))
    (direct,) = epitopelib.resolve_antigen_chains(
        ["L"], spaces, antibody_chains=["A"], entry_antibody_chains=["H", "L"]
    )
    assert (direct.chain, direct.namespace) == ("L", epitopelib.NS_AUTH)
    assert direct.usable
    # ...but the same chain reached through label space is refused
    (indirect,) = epitopelib.resolve_antigen_chains(
        ["C"], spaces, antibody_chains=["A"], entry_antibody_chains=["H", "L"]
    )
    assert (indirect.chain, indirect.namespace) == (
        "L",
        epitopelib.NS_ANTIBODY_COLLISION,
    )


@pytest.mark.network
def test_guard5_12ut_label_antigen_chain_was_being_dropped(instances):
    """The 134-identifier bug on a real entry: ``AB`` is auth ``0``.

    12UT is a 180-chain capsid. The auth-only resolver found no chain ``AB``
    and labelled instance ``1h-1l`` from auth ``w`` alone, omitting a second
    annotated VP1 copy — an epitope union silently short of its true size.
    """
    target = _structure("12ut")
    spaces = epitopelib.chain_namespaces(target)
    assert spaces.label_to_auth["AB"] == "0"
    assert "AB" not in set(spaces.auth)
    assert epitopelib.resolve_chain("AB", list(spaces.auth)) is None

    inst = next(i for i in instances if i.instance_id == "pdb_000012ut-1h-1l")
    assert inst.antigen_chains == ("AB", "w")
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains, spaces, antibody_chains=["h", "l"]
    )
    assert [r.chain for r in resolutions if r.usable] == ["0", "w"]


@pytest.mark.network
def test_guard5_12ut_case_ambiguous_antigen_is_dropped_not_guessed(instances):
    """And the wrong-molecule half: ``AH`` folded onto one of ``ah``/``Ah``.

    12UT has both. The old rule returned whichever the dict happened to hold,
    so instance ``5h-5l`` was labelled against a VP1 copy nobody annotated.
    """
    target = _structure("12ut")
    spaces = epitopelib.chain_namespaces(target)
    auth = set(spaces.auth)
    assert {"ah", "Ah"} <= auth
    assert "AH" not in auth and "AH" not in spaces.label_to_auth

    inst = next(i for i in instances if i.instance_id == "pdb_000012ut-5h-5l")
    assert "AH" in inst.antigen_chains
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains, spaces, antibody_chains=["5h", "5l"]
    )
    ah = next(r for r in resolutions if r.raw == "AH")
    assert ah.chain is None
    assert ah.namespace == epitopelib.NS_CASE_AMBIGUOUS
    assert ah.refused, "a refused chain must drop the instance, not be guessed"


@pytest.mark.network
def test_guard5_13ds_ligand_antigen_chains_are_accounted_for(instances):
    """Most of the 41.5% was this, and it was never a wrong label.

    13DS annotates ``C|G|I|M`` against types ``PROTEIN|HAPTEN``: PD-L1 plus
    three glycerol/ethanediol molecules, whose identifiers are non-polymer
    ``label_asym_id``s. They must be classified as such — accounted for and
    excluded — not reported as chains missing from the coordinates.
    """
    target = _structure("13ds")
    spaces = epitopelib.chain_namespaces(target)
    inst = next(i for i in instances if i.instance_id == "pdb_000013ds-A-B")
    resolutions = epitopelib.resolve_antigen_chains(
        inst.antigen_chains, spaces, antibody_chains=["A", "B"]
    )
    by_raw = {r.raw: r.namespace for r in resolutions}
    assert by_raw["C"] == epitopelib.NS_AUTH
    for ligand in ("G", "I", "M"):
        assert by_raw[ligand] == epitopelib.NS_NON_POLYMER
    assert not any(r.refused for r in resolutions)
    assert [r.chain for r in resolutions if r.usable] == ["C"]


# --------------------------------------------------------------------------
# validation targets
# --------------------------------------------------------------------------


@pytest.mark.network
def test_1bj1_is_the_canonical_17_residue_bevacizumab_epitope(instances):
    """The published bevacizumab epitope, including the Gly88 hotspot.

    Asserted on the *dominant chain*, not the union. The union is 19 residues
    because the Fab also grazes 2 residues of the second VEGF monomer; a paper
    quoting '17' means one monomer. Both numbers are in the manifest so the
    comparison cannot be made carelessly.
    """
    result = _epitope_for("1bj1", "pdb_00001bj1-H-L", instances)
    assert len(result.dominant_residues) == 17
    assert ResidueKey("W", 88) in result.dominant_residues
    assert ResidueKey("W", 88) in result.residues
    numbers = sorted(k.auth_seq_id for k in result.dominant_residues)
    assert numbers == [45, 48, 79, 80, 81, 82, 83, 84, 86, 87, 88, 89, 90, 91, 92, 93, 94]


@pytest.mark.network
def test_7kmg_is_the_20_residue_rbd_receptor_binding_ridge(instances):
    """The SARS-CoV-2 RBD ridge; 484-494 is the ridge proper."""
    result = _epitope_for("7kmg", "pdb_00007kmg-A-B", instances)
    assert result.size == 20
    assert result.dominant_chain == "C"
    for number in (484, 486, 487, 489, 493):
        assert ResidueKey("C", number) in result.residues


@pytest.mark.network
def test_1zvh_is_an_18_residue_vhh_epitope(instances):
    """A single-domain antibody: heavy chain only, no light chain."""
    inst = next(i for i in instances if i.instance_id == "pdb_00001zvh-A")
    assert inst.is_single_domain
    result = _epitope_for("1zvh", "pdb_00001zvh-A", instances)
    assert result.size == 18
    assert result.antibody_chains == ("A",)
    assert result.dominant_chain == "L"


@pytest.mark.network
def test_6al0_epitope_spans_insertion_codes(instances):
    """Insertion codes are not theoretical: 6AL0 chain A inserts 263A-263L.

    Note this contradicts the design spec, which states 6al0 yields a 2-residue
    lattice contact. On the asymmetric unit with no symmetry applied it yields
    14 residues: 262, 263, and 263A-263L. Twelve of them differ from 263 only by
    insertion code, so any pipeline keying residues on the integer alone
    collapses those thirteen into one and reports 2 -- which is exactly the
    number the spec quotes.
    """
    result = _epitope_for("6al0", "pdb_00006al0-H-L", instances)
    assert result.size == 14
    with_icode = [k for k in result.residues if k.has_icode]
    assert len(with_icode) == 12
    collapsed = {(k.auth_asym_id, k.auth_seq_id) for k in result.residues}
    assert len(collapsed) == 2
    assert ResidueKey("A", 263, "L") in result.residues


# --------------------------------------------------------------------------
# the snapshot and the HTML-200 trap
# --------------------------------------------------------------------------


def test_html_payload_is_rejected_not_parsed():
    """The documented legacy SAbDab URL serves a React shell with HTTP 200.

    Measured 2026-10-05: 1,456 bytes of HTML, status 200. A naive CSV reader
    parses it into single-column rows and the build 'succeeds' with no labels.
    """
    html = (
        b'<!doctype html>\n<html lang="en">\n<head><title>SAbDab2</title></head>\n'
        + b"<!-- padding -->" * 200_000
    )
    with pytest.raises(sabdab.SabdabError) as excinfo:
        sabdab._reject_non_csv(html, sabdab.LEGACY_SUMMARY_URL)
    assert "HTML" in str(excinfo.value)


def test_short_payload_is_rejected():
    with pytest.raises(sabdab.SabdabError, match="bytes"):
        sabdab._reject_non_csv(b"INSTANCE,PDB,Hchain,Lchain,antigen_chain\n", "u")


def test_csv_without_the_expected_header_is_rejected():
    payload = b"a,b,c\n" + b"1,2,3\n" * 200_000
    with pytest.raises(sabdab.SabdabError, match="header"):
        sabdab._reject_non_csv(payload, "u")


def test_snapshot_is_pinned_in_the_repo(snapshot: sabdab.Snapshot):
    """Evaluation must never depend on an undocumented live endpoint."""
    assert snapshot.n_rows == 22548
    assert snapshot.source_url == sabdab.SUMMARY_URL
    meta = json.loads((sabdab.SNAPSHOT_DIR / sabdab.SNAPSHOT_META).read_text())
    assert len(meta["sha256"]) == 64
    assert meta["http_date"]


def test_load_summary_does_not_touch_the_network_by_default(monkeypatch):
    def explode(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("load_summary reached the network")

    monkeypatch.setattr(sabdab.urllib.request, "urlopen", explode)
    assert sabdab.load_summary(allow_network=False).n_rows == 22548


def test_corrupt_snapshot_is_rejected(tmp_path: Path):
    """A silently-wrong snapshot would poison every label downstream."""
    with gzip.GzipFile(tmp_path / sabdab.SNAPSHOT_CSV, "wb") as handle:
        handle.write(b"INSTANCE,PDB,Hchain,Lchain,antigen_chain\n" * 60_000)
    (tmp_path / sabdab.SNAPSHOT_META).write_text(json.dumps({"sha256": "0" * 64}))
    with pytest.raises(sabdab.SabdabError, match="sha256"):
        sabdab.load_snapshot(tmp_path)


def test_missing_snapshot_gives_an_actionable_message(tmp_path: Path):
    with pytest.raises(sabdab.SabdabError, match="--refresh-snapshot"):
        sabdab.load_snapshot(tmp_path)


def test_short_pdb_id_handles_the_extended_form():
    assert sabdab.short_pdb_id("pdb_00001bj1") == "1bj1"
    assert sabdab.short_pdb_id("1BJ1") == "1bj1"
    with pytest.raises(sabdab.SabdabError, match="PDB id"):
        sabdab.short_pdb_id("nonsense")


def test_protein_antigen_filter_excludes_nmr_and_poor_resolution(instances):
    usable = sabdab.protein_antigen_instances(instances, max_resolution=3.5)
    assert all(i.has_protein_antigen for i in usable)
    assert all(i.resolution is not None and i.resolution <= 3.5 for i in usable)
    assert all(i.method.upper() in ("XRAY", "ELECTRON_MICROSCOPY") for i in usable)
    assert len(usable) == 12892


# --------------------------------------------------------------------------
# clustering and splits
# --------------------------------------------------------------------------


def _meta(pdb_id, chain, accessions=(), sequence="AAAA"):
    return clusterlib.ChainMeta(pdb_id, chain, "Protein", sequence, tuple(accessions))


def test_connected_antigens_cannot_cross_split_through_complex_or_sequence_alias():
    metadata = {
        ("1abc", "A"): _meta("1abc", "A", ["P1"], "AAAA"),
        ("2abc", "A"): _meta("2abc", "A", ["P1"], "AAA"),
        ("2abc", "B"): _meta("2abc", "B", ["P2"], "CCCC"),
        ("3abc", "B"): _meta("3abc", "B", (), "CCCC"),
        ("4abc", "D"): _meta("4abc", "D", ["P4"], "DDDD"),
    }
    instances = [("a", "1abc", ["A"]), ("ab", "2abc", ["A", "B"]),
                 ("b", "3abc", ["B"]), ("d", "4abc", ["D"])]
    grouped = clusterlib.assign_clusters(instances, metadata)
    assert grouped["a"] == grouped["ab"] == grouped["b"]
    assert grouped["d"] != grouped["a"]
    assert clusterlib.assign_clusters(list(reversed(instances)), metadata) == grouped
    split = clusterlib.assign_splits(grouped.values())
    assert len({split[grouped[i]] for i in ("a", "ab", "b")}) == 1


def test_unknown_antigens_share_only_the_same_entry():
    grouped = clusterlib.assign_clusters(
        [("a", "1abc", ["A"]), ("b", "1abc", ["B"]), ("c", "2abc", ["A"])], {})
    assert grouped["a"] == grouped["b"]
    assert grouped["a"] != grouped["c"]


def test_splits_are_assigned_by_cluster_never_by_complex():
    """The whole point: no cluster may appear in two splits.

    A per-complex split puts near-identical spike complexes in train and test,
    so the score measures memorisation rather than generalisation.
    """
    clusters = [f"up:P{index:05d}" for index in range(400)]
    split_of = clusterlib.assign_splits(clusters)
    assert set(split_of) == set(clusters)
    assert len(set(split_of.values())) == 3
    # Same cluster id always lands in the same split, in any ordering.
    assert split_of == clusterlib.assign_splits(reversed(clusters))


def test_splits_are_stable_when_the_benchmark_grows():
    """Adding entries must not move existing clusters between splits."""
    first = clusterlib.assign_splits([f"c{i}" for i in range(50)])
    second = clusterlib.assign_splits([f"c{i}" for i in range(100)])
    for cluster_id, split in first.items():
        assert second[cluster_id] == split


def test_split_fractions_are_roughly_respected():
    split_of = clusterlib.assign_splits([f"c{i}" for i in range(4000)])
    train = sum(1 for v in split_of.values() if v == "train") / 4000
    assert 0.66 < train < 0.74


def test_cluster_cap_is_twenty_and_logs_what_it_dropped():
    cluster_of = {f"i{index}": "up:P0DTC2" for index in range(57)}
    kept, dropped = clusterlib.cap_clusters(cluster_of, cap=clusterlib.CLUSTER_CAP)
    assert clusterlib.CLUSTER_CAP == 20
    assert len(kept) == 20
    assert len(dropped) == 37
    assert all(cluster == "up:P0DTC2" for _instance, cluster in dropped)


def test_cluster_cap_keeps_the_best_ranked_members():
    cluster_of = {f"i{index}": "c" for index in range(5)}
    resolutions = {f"i{index}": 5.0 - index for index in range(5)}
    kept, _dropped = clusterlib.cap_clusters(
        cluster_of, cap=2, rank=lambda i: (resolutions[i],)
    )
    assert set(kept) == {"i4", "i3"}


def test_macro_average_is_not_dominated_by_the_largest_cluster():
    """The reason macro-averaging is mandatory, in one assertion.

    One cluster of 100 instances scoring 0.0 and four of 1 scoring 1.0: the
    micro-average is 0.04 and the macro-average is 0.8. Spike is 17% of
    instances, so this difference is not hypothetical.
    """
    values = {f"big{i}": 0.0 for i in range(100)}
    values.update({f"small{i}": 1.0 for i in range(4)})
    cluster_of = {f"big{i}": "up:P0DTC2" for i in range(100)}
    cluster_of.update({f"small{i}": f"up:X{i}" for i in range(4)})
    macro, n_clusters = clusterlib.macro_average(values, cluster_of)
    micro = sum(values.values()) / len(values)
    assert n_clusters == 5
    assert macro == pytest.approx(0.8)
    assert micro == pytest.approx(0.0384, abs=1e-3)


def test_cluster_sizes_are_sorted_largest_first():
    cluster_of = {"a": "c1", "b": "c1", "c": "c2"}
    assert clusterlib.cluster_sizes(cluster_of) == [("c1", 2), ("c2", 1)]


# --------------------------------------------------------------------------
# manifest round-trip
# --------------------------------------------------------------------------


def test_residue_key_round_trips_including_insertion_codes():
    keys = (
        ResidueKey("W", 88),
        ResidueKey("A", 263, "L"),
        ResidueKey("PPP", -3),
        ResidueKey("AA", 405),
    )
    assert manifestlib.parse_residues(manifestlib.format_residues(keys)) == keys


def test_residue_key_format_is_unambiguous_for_digit_ending_chains():
    """Why the colon form exists: 'A1405' cannot be read back reliably."""
    key = ResidueKey("A1", 405)
    assert manifestlib.format_residue_key(key) == "A1:405"
    assert manifestlib.parse_residue_key("A1:405") == key


def test_malformed_residue_key_raises():
    for text in ("W88", "A:b", "", "A:1:2:3"):
        with pytest.raises(ValueError):
            manifestlib.parse_residue_key(text)


def test_manifest_round_trips(tmp_path: Path):
    row = manifestlib.ManifestRow(
        instance_id="pdb_00001bj1-H-L",
        pdb_id="1bj1",
        heavy_chain="H",
        light_chain="L",
        antigen_chains="V|W",
        epitope_residues="W:88;A:263:L",
        n_epitope=2,
        dominant_chain="W",
        n_epitope_dominant=1,
        cluster_id="up:P15692",
        split="train",
        cutoff_angstrom=4.5,
        method="XRAY",
        resolution="2.40",
        chain_resolution="A->L=antibody_collision|V=auth|W=auth",
    )
    path = manifestlib.write_manifest([row], tmp_path / "manifest.csv")
    back = manifestlib.read_manifest(path)
    assert back == [row]
    assert back[0].residues == (ResidueKey("W", 88), ResidueKey("A", 263, "L"))
    assert back[0].antigen_chain_list == ("V", "W")


def test_manifest_with_wrong_columns_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("pdb_id,epitope\n1bj1,W:88\n")
    with pytest.raises(ValueError, match="columns"):
        manifestlib.read_manifest(path)


def test_manifest_write_is_deterministic(tmp_path: Path):
    rows = [
        manifestlib.ManifestRow(
            f"i{index}", f"{index}abc", "H", "L", "A", "A:1", 1, "A", 1,
            "c", "train", 4.5, "XRAY", "2.00", "A=auth",
        )
        for index in (3, 1, 2)
    ]
    first = manifestlib.write_manifest(rows, tmp_path / "a.csv").read_bytes()
    second = manifestlib.write_manifest(
        list(reversed(rows)), tmp_path / "b.csv"
    ).read_bytes()
    assert first == second


def test_no_coordinates_are_committed_to_the_repo():
    """The manifest ships; 2.57 GB of coordinates do not."""
    tracked = [
        path
        for path in (REPO_ROOT / "benchmark").rglob("*")
        if path.is_file() and path.suffix in (".cif", ".pdb", ".ent", ".mmtf")
    ]
    assert tracked == []


def test_shipped_snapshot_stays_small():
    """A pinned snapshot is required; a bulk archive is not."""
    size = (sabdab.SNAPSHOT_DIR / sabdab.SNAPSHOT_CSV).stat().st_size
    assert size < 8 * 1024 * 1024, f"{size} bytes is too large to commit"


def test_data_licenses_file_credits_every_source():
    text = (REPO_ROOT / "DATA_LICENSES.md").read_text()
    for needle in (
        "10.1093/nar/gkab1050",
        "10.5281/zenodo.11495514",
        "CC0-1.0",
        "CC-BY-4.0",
        "DiscoTope-3.0",
        "SEMA",
        "Dockground",
        "BioLiP2",
        "DIPS-Plus",
    ):
        assert needle in text, f"DATA_LICENSES.md does not mention {needle}"


# --------------------------------------------------------------------------
# the measured sample
# --------------------------------------------------------------------------


@pytest.mark.network
def test_median_epitope_size_is_in_the_published_range(instances):
    """Median near 17 residues, which matches the published 15-25 norm.

    Checked on the validation entries plus the first instances of a fixed set
    of cached entries, so it runs in seconds rather than downloading 2.57 GB.
    """
    targets = [
        ("1bj1", "pdb_00001bj1-H-L"),
        ("1bj1", "pdb_00001bj1-K-J"),
        ("7kmg", "pdb_00007kmg-A-B"),
        ("7kmg", "pdb_00007kmg-D-E"),
        ("1zvh", "pdb_00001zvh-A"),
        ("6al0", "pdb_00006al0-H-L"),
    ]
    sizes = [_epitope_for(pdb, iid, instances).size for pdb, iid in targets]
    assert 12 <= float(np.median(sizes)) <= 22
    assert all(size >= epitopelib.MIN_EPITOPE_RESIDUES for size in sizes)


# --------------------------------------------------------------------------
# the CLI driver
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runner():
    from typer.testing import CliRunner

    return CliRunner()


def _driver():
    """Import the driver by path; scripts/ is not an importable package."""
    import importlib.util

    path = REPO_ROOT / "scripts" / "build_benchmark.py"
    spec = importlib.util.spec_from_file_location("build_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_touches_no_network(runner, tmp_path, monkeypatch):
    """--dry-run must plan without downloading anything."""
    module = _driver()

    def explode(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("--dry-run reached the network")

    monkeypatch.setattr(module.epitopelib.urllib.request, "urlopen", explode)
    monkeypatch.setattr(module.sabdab.urllib.request, "urlopen", explode)
    result = runner.invoke(
        module.app, ["--dry-run", "--limit", "5", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert not (tmp_path / "manifest.csv").exists()


def test_cli_limit_reports_what_it_deferred(runner, tmp_path):
    """No silent truncation: --limit says how many instances it set aside."""
    module = _driver()
    result = runner.invoke(
        module.app, ["--dry-run", "--limit", "7", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "--limit 7: deferred" in result.output
    assert "row/entry inflation 1.93x" in result.output


def test_cli_accepts_the_sensitivity_cutoff(runner, tmp_path):
    module = _driver()
    result = runner.invoke(
        module.app,
        ["--dry-run", "--limit", "1", "--cutoff", "4.0", "--out", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output


def test_cli_coords_only_needs_a_manifest(runner, tmp_path):
    module = _driver()
    result = runner.invoke(module.app, ["--coords-only", "--out", str(tmp_path)])
    assert result.exit_code != 0
    assert "no manifest" in result.output
