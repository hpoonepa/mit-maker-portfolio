# SPDX-License-Identifier: MIT
"""Tests for the numbering-reconciliation check.

The bug under test is silent. A hotspot list written for BoltzGen
(``label_seq_id``) loads without error into RFdiffusion (author numbering) and
simply aims the design at different residues. Nothing fails until the assay
does, weeks later. So most of these tests assert on the *reason* reported, not
merely on pass/fail.

Two local fixtures exist here rather than in conftest.py because they need
numbering geometries conftest's +100 offset deliberately cannot produce: a
small constant offset (where every number is valid in both schemes) and a
zero offset (where the two schemes coincide and the ambiguity is impossible).
"""

from pathlib import Path

import gemmi
import pytest

from hotspot_preflight.findings import Severity, finding_sort_key, sort_findings
from hotspot_preflight.residue import ResidueKey, parse_hotspot_spec
from hotspot_preflight.structure import load_target
from hotspot_preflight.checks.resolved import check_resolved
from hotspot_preflight.checks.numbering import (
    build_reverse_label_seq_map,
    check_numbering,
    translate_for_tools,
)

_COMPS = ["GLY", "ALA", "VAL", "LEU", "ILE", "PHE"]


def _write_cif(
    path: Path,
    residues: list[tuple[int, int, str]],
    n_declared: int | None = None,
) -> Path:
    """Write a one-chain mmCIF from explicit ``(label_seq, auth_seq, icode)``.

    Goes through gemmi's own writer so the fixture exercises the same parse
    path as a real file, matching conftest.py's approach.
    """
    st = gemmi.Structure()
    st.name = "TEST"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")

    for label_seq, auth_seq, icode in residues:
        res = gemmi.Residue()
        res.name = _COMPS[(label_seq - 1) % len(_COMPS)]
        res.seqid = gemmi.SeqId(auth_seq, icode)
        res.label_seq = label_seq
        res.het_flag = "A"
        res.entity_type = gemmi.EntityType.Polymer
        for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5), ("C", "C", 3.0)):
            atom = gemmi.Atom()
            atom.name = name
            atom.element = gemmi.Element(elem)
            atom.pos = gemmi.Position(label_seq * 6.0 + dx, 0.0, 0.0)
            atom.occ = 1.0
            atom.b_iso = 20.0
            res.add_atom(atom)
        chain.add_residue(res)

    model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    declared = n_declared if n_declared is not None else len(residues)
    for entity in st.entities:
        if entity.entity_type == gemmi.EntityType.Polymer:
            entity.full_sequence = [
                _COMPS[i % len(_COMPS)] for i in range(declared)
            ]
    path.write_text(st.make_mmcif_document().as_string())
    return path


@pytest.fixture
def cif_offset_two(tmp_path: Path) -> Path:
    """author = label_seq + 2, so 3 and 4 are valid in BOTH schemes.

    This is the geometry that makes AMBIGUOUS_NUMBERING a real hazard: author 3
    is label_seq 1, while label_seq 3 is author 5. Both readings name a real
    residue and they are different residues.
    """
    return _write_cif(
        tmp_path / "offset2.cif",
        [(1, 3, " "), (2, 4, " "), (3, 5, " "), (4, 6, " ")],
    )


@pytest.fixture
def cif_offset_zero(tmp_path: Path) -> Path:
    """author == label_seq. The two schemes coincide, so the bug cannot occur."""
    return _write_cif(
        tmp_path / "offset0.cif",
        [(1, 1, " "), (2, 2, " "), (3, 3, " "), (4, 4, " ")],
    )


@pytest.fixture
def cif_with_icode(tmp_path: Path) -> Path:
    """Author numbering containing 4A, which RFdiffusion cannot express.

    The numbers are small on purpose: author 4 sits inside this chain's
    label_seq range (1-4), so a check that read the icode key's number as a
    label_seq would find a second, different residue and wrongly cry ambiguity.
    An earlier version of this fixture used author 102A, which is outside the
    label range — the guard against that misreading was then unfalsifiable, and
    a mutation removing it survived the whole battery.
    """
    return _write_cif(
        tmp_path / "icode.cif",
        [(1, 3, " "), (2, 4, " "), (3, 4, "A"), (4, 5, " ")],
    )


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def _only(findings, code):
    matches = [f for f in findings if f.code == code]
    assert len(matches) == 1, f"expected exactly one {code}, got {_codes(findings)}"
    return matches[0]


class TestReverseMap:
    def test_inverts_the_author_to_label_map(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        rev = build_reverse_label_seq_map(t)
        assert rev[("A", 1)] == ResidueKey("A", 101)
        assert rev[("A", 6)] == ResidueKey("A", 106)

    def test_unmodelled_label_seq_absent(self, cif_with_unobs_category):
        """label_seq 4 and 5 are declared but have no coordinates, so they
        cannot be translated for BoltzGen and must not appear."""
        t = load_target(cif_with_unobs_category)
        rev = build_reverse_label_seq_map(t)
        assert ("A", 4) not in rev


class TestWrongScheme:
    def test_label_seq_style_number_is_killed(self, cif_with_unobs_category):
        """"A1" does not exist in author numbering but label_seq 1 does. That is
        a hotspot list pasted out of a BoltzGen config."""
        t = load_target(cif_with_unobs_category)
        findings = check_numbering(t, [ResidueKey("A", 1)])
        f = _only(findings, "WRONG_NUMBERING_SCHEME")
        assert f.severity is Severity.KILL
        assert "A101" in f.message
        assert "label_seq" in f.message
        assert f.evidence["label_seq_interpretation"] == "A101"
        assert f.evidence["author_interpretation"] is None
        assert f.evidence["chain_offset"] == 100

    def test_author_number_passes(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        findings = check_numbering(t, [ResidueKey("A", 101)])
        f = _only(findings, "NUMBERING_CONSISTENT")
        assert f.severity is Severity.PASS
        assert f.evidence["label_seq"] == 1

    def test_unknown_number_killed_with_both_ranges(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        findings = check_numbering(t, [ResidueKey("A", 999)])
        f = _only(findings, "NO_SUCH_RESIDUE")
        assert f.severity is Severity.KILL
        assert f.evidence["author_range"] == [101, 106]
        assert f.evidence["label_seq_range"] == [1, 6]

    def test_declared_but_unmodelled_is_not_a_numbering_error(
        self, cif_with_unobs_category
    ):
        """Author 104 is declared in the entry and simply has no coordinates.

        The reverse label_seq map is built from coordinates, so without
        consulting the declared sequence this residue looks exactly like a
        nonexistent one — and the check would tell the user, confidently and
        wrongly, that their numbering is bad. It is not: the number is correct
        and the residue is unmodelled, which is the resolved check's verdict to
        give, not ours.
        """
        t = load_target(cif_with_unobs_category)
        findings = check_numbering(t, [ResidueKey("A", 104)])
        f = _only(findings, "RESIDUE_DECLARED_NOT_OBSERVED")
        assert f.severity is Severity.WARN
        assert "NO_SUCH_RESIDUE" not in _codes(findings)
        assert "WRONG_NUMBERING_SCHEME" not in _codes(findings)
        assert f.evidence["declared"] is True
        assert f.evidence["observed"] is False
        assert f.evidence["label_seq"] is None
        assert "resolved" in f.message
        assert "label_seq_id" in f.message

    def test_warns_rather_than_adding_a_second_kill(self, cif_without_unobs_category):
        """Two checks must not both KILL for one underlying fact, so this stays
        a WARN even on an entry that omits the _pdbx_unobs category — the gap is
        then derived from declared-minus-observed."""
        t = load_target(cif_without_unobs_category)
        findings = check_numbering(t, parse_hotspot_spec("A104,A105"))
        assert set(_codes(findings)) == {"RESIDUE_DECLARED_NOT_OBSERVED"}
        assert not [f for f in findings if f.severity is Severity.KILL]

    def test_absent_from_declared_sequence_still_kills(self, cif_with_unobs_category):
        """NO_SUCH_RESIDUE is reserved for genuinely absent residues. Author 107
        is past the end of the declared sequence, so nothing in the entry
        supports it and KILL is the honest verdict."""
        t = load_target(cif_with_unobs_category)
        f = _only(check_numbering(t, [ResidueKey("A", 107)]), "NO_SUCH_RESIDUE")
        assert f.severity is Severity.KILL

    def test_zero_offset_entry_cannot_show_the_bug(self, cif_offset_zero):
        """When author == label_seq the two schemes are indistinguishable, so
        neither WRONG_NUMBERING_SCHEME nor AMBIGUOUS_NUMBERING can fire."""
        t = load_target(cif_offset_zero)
        findings = check_numbering(t, parse_hotspot_spec("A1-4"))
        assert set(_codes(findings)) == {"NUMBERING_CONSISTENT"}
        assert all(f.evidence["chain_offset"] == 0 for f in findings)


class TestAmbiguous:
    def test_reports_both_candidates(self, cif_offset_two):
        t = load_target(cif_offset_two)
        findings = check_numbering(t, [ResidueKey("A", 3)])
        f = _only(findings, "AMBIGUOUS_NUMBERING")
        assert f.severity is Severity.WARN
        # Author 3 is label_seq 1; label_seq 3 is author 5. Both are real.
        assert f.evidence["author_interpretation"] == "A3"
        assert f.evidence["label_seq_interpretation"] == "A5"
        assert f.evidence["chain_offset"] == 2
        assert "A3" in f.message and "A5" in f.message

    def test_number_outside_label_range_is_unambiguous(self, cif_offset_two):
        """Author 6 is real; label_seq 6 does not exist on this chain, so there
        is only one reading and no warning."""
        t = load_target(cif_offset_two)
        findings = check_numbering(t, [ResidueKey("A", 6)])
        assert _codes(findings) == ["NUMBERING_CONSISTENT"]


class TestChain:
    def test_unknown_chain_killed(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        f = _only(check_numbering(t, [ResidueKey("Z", 101)]), "NO_SUCH_CHAIN")
        assert f.severity is Severity.KILL
        assert f.evidence["chains"] == ["A"]

    def test_case_mismatch_named_explicitly(self, cif_with_unobs_category):
        """mmCIF chain ids are case-sensitive and 'a' is a common typo for 'A'.
        Saying so turns a dead end into a one-character fix."""
        t = load_target(cif_with_unobs_category)
        f = _only(check_numbering(t, [ResidueKey("a", 101)]), "NO_SUCH_CHAIN")
        assert f.evidence["case_insensitive_match"] == "A"
        assert "case" in f.message.lower()

    def test_bad_chain_suppresses_residue_verdict(self, cif_with_unobs_category):
        """With the wrong chain the number means nothing, so we do not also
        claim the residue is missing."""
        t = load_target(cif_with_unobs_category)
        codes = _codes(check_numbering(t, [ResidueKey("Z", 1)]))
        assert codes == ["NO_SUCH_CHAIN"]


class TestIcode:
    def test_insertion_code_warns_and_names_tools(self, cif_with_icode):
        t = load_target(cif_with_icode)
        findings = check_numbering(t, [ResidueKey("A", 4, "A")])
        f = _only(findings, "ICODE_NOT_EXPRESSIBLE")
        assert f.severity is Severity.WARN
        assert f.evidence["affected_tools"] == ["rfdiffusion"]
        assert "rfdiffusion" in f.message.lower()
        # The residue itself is real, so it still resolves cleanly.
        assert "NUMBERING_CONSISTENT" in _codes(findings)

    def test_icode_key_is_never_read_as_label_seq(self, cif_with_icode):
        """label_seq_id has no insertion codes, so a key carrying one is author
        numbering by construction and has no second reading.

        Author 4 is also a valid label_seq here (pointing at author 5), so a
        check that ignored the icode would report a spurious ambiguity.
        """
        t = load_target(cif_with_icode)
        codes = _codes(check_numbering(t, [ResidueKey("A", 4, "A")]))
        assert "AMBIGUOUS_NUMBERING" not in codes
        assert "WRONG_NUMBERING_SCHEME" not in codes

    def test_translate_explains_rfdiffusion_but_still_emits_bindcraft(
        self, cif_with_icode
    ):
        t = load_target(cif_with_icode)
        out = translate_for_tools(t, [ResidueKey("A", 4, "A")])
        assert "cannot express" in out["rfdiffusion"]
        assert out["bindcraft"] == "A4A"
        assert out["boltzgen"] == "A3"


class TestTranslateForTools:
    def test_boltzgen_uses_label_seq_while_rfdiffusion_uses_author(
        self, cif_with_unobs_category
    ):
        """THE demonstration of the bug class this tool exists to prevent.

        One hotspot list, author residues 101 and 102 of chain A. The same two
        residues must be written two different ways:

          RFdiffusion / BindCraft -> author numbers      101, 102
          BoltzGen                -> label_seq_id        1, 2

        A user who pastes "[A101,A102]" into a BoltzGen config has asked for
        author residues 101 and 102 but will get label_seq 101 and 102, which
        on this entry do not exist at all. A user who pastes "A1,A2" into
        RFdiffusion aims at nothing. Neither tool complains.
        """
        t = load_target(cif_with_unobs_category)
        keys = parse_hotspot_spec("A101,A102")
        out = translate_for_tools(t, keys)
        assert out["rfdiffusion"] == "[A101,A102]"
        assert out["bindcraft"] == "A101-102"
        assert out["boltzgen"] == "A1,A2"
        # The two strings share no number: that is the whole point.
        assert out["boltzgen"] != out["bindcraft"]

    def test_unresolvable_residue_gives_reason_not_exception(
        self, cif_with_unobs_category
    ):
        """A residue with no coordinates has no label_seq to emit. The caller
        still wants the formats that do work, so the failure is a string."""
        t = load_target(cif_with_unobs_category)
        out = translate_for_tools(t, [ResidueKey("A", 104)])
        assert out["rfdiffusion"] == "[A104]"
        assert "A104" in out["boltzgen"]
        assert "label_seq" in out["boltzgen"]


class TestOrdering:
    def test_check_preserves_caller_order(self, cif_with_unobs_category):
        """The check reports what it found in the order it was asked.

        ``parse_hotspot_spec`` preserves first-seen order because that order
        sometimes encodes the user's priority. A check that sorted internally
        would discard that, and presentation order is the aggregator's call,
        not this check's — so these keys must come back deliberately unsorted.
        """
        t = load_target(cif_with_unobs_category)
        keys = [ResidueKey("A", 106), ResidueKey("A", 101), ResidueKey("A", 103)]
        findings = check_numbering(t, keys)
        assert [f.key for f in findings] == keys

    def test_canonical_order_comes_from_sort_findings(self, cif_with_unobs_category):
        """Piping through the package's one sort definition is what makes the
        output stable, regardless of the order the caller asked in."""
        t = load_target(cif_with_unobs_category)
        keys = [ResidueKey("A", 999), ResidueKey("A", 1), ResidueKey("A", 101)]
        forward = sort_findings(check_numbering(t, keys))
        backward = sort_findings(check_numbering(t, list(reversed(keys))))
        assert [f.to_dict() for f in forward] == [f.to_dict() for f in backward]
        assert [(f.key.auth_seq_id, f.code) for f in forward] == [
            (1, "WRONG_NUMBERING_SCHEME"),
            (101, "NUMBERING_CONSISTENT"),
            (999, "NO_SUCH_RESIDUE"),
        ]

    def test_sort_is_total_over_this_checks_findings(self, cif_with_icode):
        """Two findings on one residue (icode WARN plus its resolution verdict)
        must still order deterministically — the case where a naive
        ``(key is None, key, code)`` sort would compare None against None."""
        t = load_target(cif_with_icode)
        findings = check_numbering(t, [ResidueKey("A", 4, "A")])
        keys = [finding_sort_key(f) for f in sort_findings(findings)]
        assert keys == sorted(keys)
        assert len(set(keys)) == len(keys)


@pytest.mark.network
class TestReal6F5J:
    def test_offset_zero_chain_stays_silent(self, real_6f5j):
        """On 6F5J chain C the author number equals label_seq (verified: seq_id
        398 is author 398). The check must therefore report nothing but PASS —
        a checker that cries wrong-scheme here would be useless in practice."""
        t = load_target(real_6f5j)
        findings = check_numbering(t, parse_hotspot_spec("C300,C302,C346"))
        assert set(_codes(findings)) == {"NUMBERING_CONSISTENT"}
        assert all(f.severity is Severity.PASS for f in findings)

    def test_no_wrong_scheme_anywhere_on_chain_c(self, real_6f5j):
        t = load_target(real_6f5j)
        findings = check_numbering(t, parse_hotspot_spec("C300-320"))
        assert "WRONG_NUMBERING_SCHEME" not in _codes(findings)
        assert "AMBIGUOUS_NUMBERING" not in _codes(findings)

    def test_unmodelled_hotspot_yields_exactly_one_kill(self, real_6f5j):
        """The flagship CLI case: `--hotspots C405,C408` on 6F5J.

        C405 is in the virion-unresolved tail — declared, never modelled. It
        used to draw two KILLs, one of them from this check claiming the
        numbering was wrong. The numbering is fine. Exactly one KILL should
        survive, and it must come from the check that owns the fact.
        """
        t = load_target(real_6f5j)
        keys = parse_hotspot_spec("C405,C408")
        findings = check_numbering(t, keys) + check_resolved(t, keys)

        kills = [f for f in findings if f.severity is Severity.KILL]
        per_residue = [f for f in kills if f.key == ResidueKey("C", 405)]
        assert [f.check for f in per_residue] == ["resolved"]
        assert [f.code for f in per_residue] == ["UNMODELLED"]

        ours = check_numbering(t, keys)
        assert not [f for f in ours if f.severity is Severity.KILL]
        assert set(_codes(ours)) == {"RESIDUE_DECLARED_NOT_OBSERVED"}

    def test_boltzgen_matches_author_numbering_at_zero_offset(self, real_6f5j):
        """Offset 0 is why 6F5J never exposed this bug to us by accident."""
        t = load_target(real_6f5j)
        out = translate_for_tools(t, parse_hotspot_spec("C300,C302"))
        assert out["boltzgen"] == "C300,C302"
        assert out["rfdiffusion"] == "[C300,C302]"
