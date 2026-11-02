# SPDX-License-Identifier: MIT
"""Tests for the synthetic-biology standards adapters.

The SBOL tests are split deliberately. The numbering layer — index maps and
one-letter sequences — is pure ``gemmi`` and runs without the optional
``sbol3`` dependency, because that layer is the part that has to be right.
Only the tests that actually serialise a document are skipped when ``sbol3``
is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hotspot_preflight.residue import ResidueKey, parse_hotspot_spec
from hotspot_preflight.standards import rfc, sbol
from hotspot_preflight.structure import load_target

HAS_SBOL3 = sbol.sbol3_available()
needs_sbol3 = pytest.mark.skipif(
    not HAS_SBOL3,
    reason="sbol3 is not installed; install the 'sbol' extra: pip install 'hotspot-preflight[sbol]'",
)


# --------------------------------------------------------------------------
# The numbering layer. No sbol3 required.
# --------------------------------------------------------------------------


def test_index_map_covers_the_gap_and_the_offset(cif_without_unobs_category: Path):
    """An SBOL Range index is the position in the stored string, not the author number.

    The fixture's author numbering is label_seq + 100 and residues 104/105 are
    declared but unmodelled. Both traps are asserted explicitly: A101 is index
    1 (not 101), and A106 is index 6 (not index 4, which is what indexing the
    *observed* sequence "GAVF" would give).
    """
    target = load_target(cif_without_unobs_category)
    index_map = sbol.sequence_index_map(target, "A")

    assert index_map == {
        ResidueKey("A", 101): 1,
        ResidueKey("A", 102): 2,
        ResidueKey("A", 103): 3,
        ResidueKey("A", 104): 4,
        ResidueKey("A", 105): 5,
        ResidueKey("A", 106): 6,
    }
    # The two statements that matter, said out loud.
    assert index_map[ResidueKey("A", 101)] != 101
    assert index_map[ResidueKey("A", 106)] == 6


def test_chain_sequence_is_the_declared_sequence(cif_without_unobs_category: Path):
    """We index the declared (SEQRES) sequence, gaps included."""
    target = load_target(cif_without_unobs_category)
    assert sbol.chain_sequence(target, "A") == "GAVLIF"


def test_chain_sequence_and_index_map_agree(cif_without_unobs_category: Path):
    target = load_target(cif_without_unobs_category)
    seq = sbol.chain_sequence(target, "A")
    index_map = sbol.sequence_index_map(target, "A")
    expected = {101: "G", 102: "A", 103: "V", 104: "L", 105: "I", 106: "F"}
    for num, letter in expected.items():
        idx = index_map[ResidueKey("A", num)]
        assert seq[idx - 1] == letter, f"A{num} -> index {idx}"


def test_unknown_chain_raises(cif_without_unobs_category: Path):
    target = load_target(cif_without_unobs_category)
    with pytest.raises(sbol.NumberingMapError, match="chain 'Z'"):
        sbol.sequence_index_map(target, "Z")


def test_module_declares_the_role_uri_as_a_proposal():
    """The honesty constraint, enforced.

    There is no SO or GO term for a binding hotspot residue. The module must
    say so rather than implying the URI is an existing standard.
    """
    doc = sbol.__doc__ or ""
    assert "proposed" in doc.lower()
    assert "SEP 033" in doc
    assert sbol.HOTSPOT_ROLE_URI


# --------------------------------------------------------------------------
# Serialisation. Needs sbol3.
# --------------------------------------------------------------------------


def test_missing_sbol3_raises_an_actionable_error(
    cif_without_unobs_category: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Setting sys.modules[name] = None makes `import name` raise ImportError."""
    monkeypatch.setitem(sys.modules, "sbol3", None)
    target = load_target(cif_without_unobs_category)
    with pytest.raises(sbol.SbolUnavailableError, match=r"\[sbol\]"):
        sbol.write_sbol(target, "A", [ResidueKey("A", 103)], tmp_path / "x.nt")


@needs_sbol3
def test_written_ranges_point_at_the_right_amino_acids(
    cif_without_unobs_category: Path, tmp_path: Path
):
    """Re-read the file and check each Range against the stored sequence."""
    import sbol3

    target = load_target(cif_without_unobs_category)
    out = tmp_path / "target.nt"
    keys = parse_hotspot_spec("A103,A106")
    sbol.write_sbol(target, "A", keys, out)

    doc = sbol3.Document()
    doc.read(str(out))
    assert list(doc.validate().errors) == []

    sequences = {str(s.identity): s for s in doc.objects if isinstance(s, sbol3.Sequence)}
    components = [o for o in doc.objects if isinstance(o, sbol3.Component)]
    assert len(components) == 1
    component = components[0]
    assert component.display_id == "target_A"
    assert sbol3.SBO_PROTEIN in component.types

    elements = sequences[str(component.sequences[0])].elements
    assert elements == "GAVLIF"

    found: dict[str, str] = {}
    for feature in component.features:
        if sbol.HOTSPOT_ROLE_URI not in feature.roles:
            continue
        (location,) = feature.locations
        assert location.start == location.end, "one residue per hotspot feature"
        found[feature.name] = elements[location.start - 1 : location.end]

    # A103 is Val at index 3; A106 is Phe at index 6 across the 104/105 gap.
    assert found == {"hotspot_A103": "V", "hotspot_A106": "F"}


@needs_sbol3
def test_unmappable_hotspot_raises_rather_than_emitting_a_wrong_index(
    cif_without_unobs_category: Path, tmp_path: Path
):
    target = load_target(cif_without_unobs_category)
    with pytest.raises(sbol.NumberingMapError, match="A999"):
        sbol.write_sbol(target, "A", [ResidueKey("A", 999)], tmp_path / "x.nt")


@needs_sbol3
def test_hotspot_on_another_chain_raises(
    cif_without_unobs_category: Path, tmp_path: Path
):
    target = load_target(cif_without_unobs_category)
    with pytest.raises(sbol.NumberingMapError, match="chain"):
        sbol.write_sbol(target, "A", [ResidueKey("B", 103)], tmp_path / "x.nt")


@needs_sbol3
def test_read_construct_round_trips_a_written_range(
    cif_without_unobs_category: Path, tmp_path: Path
):
    target = load_target(cif_without_unobs_category)
    out = tmp_path / "target.nt"
    sbol.write_sbol(target, "A", [ResidueKey("A", 103)], out)

    chain_ish, first, last = sbol.read_construct(out)
    assert (chain_ish, first, last) == ("A", 1, 6)


@needs_sbol3
def test_construct_crop_range_is_in_author_numbering(
    cif_without_unobs_category: Path, tmp_path: Path
):
    """The conversion that stops read_construct being a numbering footgun.

    read_construct returns sequence indices (1..6). check_burial wants author
    numbers (101..106). Handing the former straight to the latter is exactly
    the silent misaim this package exists to prevent.
    """
    target = load_target(cif_without_unobs_category)
    out = tmp_path / "target.nt"
    sbol.write_sbol(target, "A", [ResidueKey("A", 103)], out)

    assert sbol.construct_crop_range(target, "A", out) == ("A", 101, 106)


@needs_sbol3
def test_read_construct_without_a_range_raises(tmp_path: Path):
    import sbol3

    ns = "https://n.example/ns"
    seq = sbol3.Sequence(
        f"{ns}/c_sequence",
        elements="GAVLIF",
        encoding=sbol3.IUPAC_PROTEIN_ENCODING,
        namespace=ns,
    )
    component = sbol3.Component(
        f"{ns}/c", sbol3.SBO_PROTEIN, sequences=[seq], namespace=ns
    )
    doc = sbol3.Document()
    doc.add(seq)
    doc.add(component)
    out = tmp_path / "bare.nt"
    doc.write(str(out), sbol3.SORTED_NTRIPLES)

    with pytest.raises(sbol.ConstructReadError, match="no SequenceFeature"):
        sbol.read_construct(out)


@needs_sbol3
@pytest.mark.network
def test_6f5j_chain_c_hotspots_land_on_the_expected_residues(
    real_6f5j: Path, tmp_path: Path
):
    """Real entry, real numbering. Chain C 325/326 must come back as Q and P."""
    import sbol3

    target = load_target(real_6f5j)
    out = tmp_path / "6f5j_C.nt"
    sbol.write_sbol(target, "C", parse_hotspot_spec("C325,C326"), out)

    doc = sbol3.Document()
    doc.read(str(out))
    assert list(doc.validate().errors) == []

    (component,) = [o for o in doc.objects if isinstance(o, sbol3.Component)]
    (sequence,) = [o for o in doc.objects if isinstance(o, sbol3.Sequence)]
    elements = sequence.elements
    assert len(elements) == 416

    found = {
        feature.name: elements[feature.locations[0].start - 1]
        for feature in component.features
        if sbol.HOTSPOT_ROLE_URI in feature.roles
    }
    assert found == {"hotspot_C325": "Q", "hotspot_C326": "P"}


# --------------------------------------------------------------------------
# RFC 10 / RFC 1000
# --------------------------------------------------------------------------


def test_rfc10_sites_are_all_palindromic():
    """Proves the one-strand claim instead of asserting it.

    A palindromic recognition site is its own reverse complement, so a
    forward-strand scan cannot miss a reverse-strand occurrence.
    """
    for name, site in {**rfc.RFC10_FORBIDDEN, **rfc.RFC10_DISCOURAGED}.items():
        assert rfc.reverse_complement(site) == site, name


def test_rfc1000_sites_are_not_palindromic():
    for name, site in rfc.RFC1000_FORBIDDEN.items():
        assert rfc.reverse_complement(site) != site, name


def test_find_sites_finds_a_planted_ecori_site():
    dna = "ATGAAA" + "GAATTC" + "AAATAA"
    assert rfc.find_sites(dna, rfc.RFC10_FORBIDDEN, both_strands=False) == [
        ("EcoRI", 6)
    ]


def test_find_sites_finds_overlapping_occurrences():
    # CTGCAG twice, overlapping at the shared CAG/CTG boundary is impossible,
    # so use a tandem repeat that does overlap: ACTAGTACTAGT shares nothing,
    # whereas AAA in a run of four overlaps three times.
    assert rfc.find_sites("AAAA", {"polyA": "AAA"}, both_strands=False) == [
        ("polyA", 0),
        ("polyA", 1),
    ]


def test_reverse_strand_bsai_is_found_only_when_both_strands_are_scanned():
    """The obvious bug, pinned.

    GAGACC is the reverse complement of BsaI's GGTCTC. A single-strand scan
    for GGTCTC cannot see it; a both-strands scan must.
    """
    dna = "ATGAAA" + "GAGACC" + "AAATAA"
    assert "GGTCTC" not in dna

    one_strand = rfc.find_sites(dna, rfc.RFC1000_FORBIDDEN, both_strands=False)
    assert one_strand == [], "single-strand scan must miss the reverse-strand site"

    both = rfc.find_sites(dna, rfc.RFC1000_FORBIDDEN, both_strands=True)
    assert both == [("BsaI", 6)]


def test_reverse_strand_sapi_is_found_only_when_both_strands_are_scanned():
    dna = "ATG" + "GAAGAGC" + "TAA"
    assert rfc.find_sites(dna, rfc.RFC1000_FORBIDDEN, both_strands=False) == []
    assert rfc.find_sites(dna, rfc.RFC1000_FORBIDDEN, both_strands=True) == [
        ("SapI", 3)
    ]


def test_check_rfc_compliance_reports_the_reverse_strand_site_for_rfc1000():
    dna = "ATGAAA" + "GAGACC" + "AAATAA"
    assert rfc.check_rfc_compliance(dna, "RFC10") == []
    messages = rfc.check_rfc_compliance(dna, "RFC1000")
    assert len(messages) == 1
    assert "BsaI" in messages[0]


def test_check_rfc_compliance_flags_notI_as_discouraged_not_illegal():
    dna = "ATG" + "GCGGCCGC" + "TAA"
    (message,) = rfc.check_rfc_compliance(dna, "RFC10")
    assert "NotI" in message
    assert "discouraged" in message.lower()
    assert "forbidden" not in message.lower()


def test_check_rfc_compliance_rejects_an_unknown_standard():
    with pytest.raises(ValueError, match="RFC10"):
        rfc.check_rfc_compliance("ATG", "RFC999")


def test_check_rfc_compliance_rejects_non_dna():
    with pytest.raises(ValueError, match="position 3"):
        rfc.check_rfc_compliance("ATGXAA", "RFC10")


def test_translate_round_trips_the_genetic_code():
    assert rfc.translate("ATGGGCTAA") == "MG*"
    with pytest.raises(ValueError, match="multiple of 3"):
        rfc.translate("ATGG")


PROTEIN = "MSNELFKRQYVPIDAATWHGCLSEKMRDFYNTIGEVLHDSEFLAQRLSEF"


def test_reverse_translate_preserves_the_protein_and_avoids_forbidden_sites():
    dna = rfc.reverse_translate(PROTEIN, forbidden=rfc.RFC10_FORBIDDEN)
    assert rfc.translate(dna) == PROTEIN
    assert len(dna) == 3 * len(PROTEIN)
    assert rfc.find_sites(dna, rfc.RFC10_FORBIDDEN, both_strands=True) == []


def test_reverse_translate_avoids_type_iis_sites_on_both_strands():
    dna = rfc.reverse_translate(PROTEIN, forbidden=rfc.RFC1000_FORBIDDEN)
    assert rfc.translate(dna) == PROTEIN
    assert rfc.find_sites(dna, rfc.RFC1000_FORBIDDEN, both_strands=True) == []


def test_reverse_translate_is_deterministic_for_a_fixed_seed():
    a = rfc.reverse_translate(PROTEIN, forbidden=rfc.RFC10_FORBIDDEN, seed=7)
    b = rfc.reverse_translate(PROTEIN, forbidden=rfc.RFC10_FORBIDDEN, seed=7)
    assert a == b
    c = rfc.reverse_translate(PROTEIN, forbidden=rfc.RFC10_FORBIDDEN, seed=8)
    assert rfc.translate(c) == PROTEIN  # a different seed is still correct


# Starts with Ser and ends with Glu, deliberately. Ser's preferred codons
# begin TC and Glu's begin GAA, so with the flanks below both seams are live.
SEAM_PROTEIN = "SEKMRDFYNTIGEVLHDSEFLAQRLSE"
SEAM_PREFIX = "AAAGAAT"  # ends GAAT: + TC from a Ser codon makes GAATTC
SEAM_SUFFIX = "TTCAAA"  # starts TTC: GAA from a Glu codon makes GAATTC


def test_reverse_translate_scans_across_the_prefix_and_suffix_seams():
    """A clean CDS can still be illegal once it is cloned into a scar.

    The seam sites exist in neither the part nor the flank alone, so only a
    junction-aware scan can see them. Both ends are checked, and the two
    concrete consequences are asserted directly: the CDS may not start ``TC``
    against this prefix, nor end ``GAA`` against this suffix.
    """
    dna = rfc.reverse_translate(
        SEAM_PROTEIN,
        forbidden=rfc.RFC10_FORBIDDEN,
        prefix=SEAM_PREFIX,
        suffix=SEAM_SUFFIX,
    )
    assert rfc.translate(dna) == SEAM_PROTEIN
    assert not dna.startswith("TC"), "EcoRI across the 5' seam"
    assert not dna.endswith("GAA"), "EcoRI across the 3' seam"

    full = SEAM_PREFIX + dna + SEAM_SUFFIX
    insert = range(len(SEAM_PREFIX), len(SEAM_PREFIX) + len(dna))
    for name, pos in rfc.find_sites(full, rfc.RFC10_FORBIDDEN, both_strands=True):
        span = range(pos, pos + len(rfc.RFC10_FORBIDDEN[name]))
        assert not (set(span) & set(insert)), f"{name} at {pos} touches the insert"


def test_reverse_translate_without_flanks_leaves_the_seams_broken():
    """Proves the seam test above is not vacuous.

    The same protein and seed, reverse-translated with no flanks supplied,
    does land on a seam-creating codon — so the flank-aware run genuinely had
    to steer away from one.
    """
    naive = rfc.reverse_translate(SEAM_PROTEIN, forbidden=rfc.RFC10_FORBIDDEN)
    assert naive.startswith("TC") or naive.endswith("GAA")
    full = SEAM_PREFIX + naive + SEAM_SUFFIX
    assert rfc.find_sites(full, rfc.RFC10_FORBIDDEN, both_strands=True)


def test_reverse_translate_does_not_try_to_fix_sites_inside_the_flanks():
    """The RFC 10 prefix and suffix contain EcoRI, XbaI, SpeI, PstI and NotI by
    construction. Treating those as violations would make the function loop
    forever on a perfectly legal part."""
    prefix = "GAATTCGCGGCCGC"  # EcoRI + NotI, as the real prefix carries them
    dna = rfc.reverse_translate("MGS", forbidden=rfc.RFC10_FORBIDDEN, prefix=prefix)
    assert rfc.translate(dna) == "MGS"


def test_reverse_translate_reports_an_unavoidable_site_instead_of_looping():
    """Met has exactly one codon, so forbidding ATG is unsatisfiable."""
    with pytest.raises(rfc.ReverseTranslationError) as excinfo:
        rfc.reverse_translate("MG", forbidden={"fake": "ATG"})
    message = str(excinfo.value)
    assert "codon 1" in message
    assert "fake" in message


def test_reverse_translate_rejects_unknown_residues_and_tables():
    with pytest.raises(ValueError, match="'Z'"):
        rfc.reverse_translate("MZ", forbidden=rfc.RFC10_FORBIDDEN)
    with pytest.raises(ValueError, match="e_coli"):
        rfc.reverse_translate("MG", forbidden={}, codon_table="yeast")
