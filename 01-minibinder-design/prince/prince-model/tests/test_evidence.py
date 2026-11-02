# SPDX-License-Identifier: MIT
"""Tests for the literature-evidence layer.

The tests that matter most here are not the happy paths. They are:

* :func:`test_unreviewed_row_cannot_change_a_verdict` and
  :func:`test_verdict_path_rejects_unreviewed_rows` — together they are the
  review gate. The first fails if the filter is deleted; the second fails if the
  filter is *moved* somewhere a future refactor could route around.
* :func:`test_missing_source_is_a_load_error` and friends — a row without
  provenance must not load at all, because the whole point of a curated table is
  that every claim can be chased back to a paper.
* :func:`test_shipped_dwv_table_loads` — the file we actually ship is parsed and
  validated by the same code path as any other table, so a typo in curation is a
  test failure rather than a silent wrong verdict.
"""

from __future__ import annotations

import importlib
import json
import socket
from pathlib import Path

import pytest

from hotspot_preflight.evidence.table import (
    BUNDLED_TABLE_DIR,
    Direction,
    EvidenceClass,
    EvidenceRow,
    EvidenceTableError,
    UnreviewedRowError,
    check_evidence,
    load_table,
    row_from_mapping,
    rows_for,
    verdict_findings,
)
from hotspot_preflight.findings import Severity
from hotspot_preflight.residue import ResidueKey

D294 = ResidueKey("C", 294)
H277 = ResidueKey("C", 277)
S278 = ResidueKey("C", 278)
Y346 = ResidueKey("C", 346)


def _row(
    residues: tuple[ResidueKey, ...] = (D294,),
    *,
    claim: str = "a claim",
    source: str = "10.1073/pnas.1615695114",
    evidence_class: EvidenceClass = EvidenceClass.ASSERTION,
    direction: Direction = Direction.SUPPORTS,
    reviewed: bool = True,
    reviewer: str = "test-curator",
    notes: str = "",
) -> EvidenceRow:
    return EvidenceRow(
        residues=residues,
        claim=claim,
        source=source,
        evidence_class=evidence_class,
        direction=direction,
        reviewed=reviewed,
        reviewer=reviewer if reviewed else "",
        notes=notes,
    )


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def _write(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


# --------------------------------------------------------------------------
# The review gate
# --------------------------------------------------------------------------


def test_unreviewed_row_cannot_change_a_verdict() -> None:
    """An unreviewed REFUTES row is strictly stronger than the reviewed row.

    If the ``reviewed`` filter were removed, the FUNCTIONAL_ASSAY/REFUTES row
    would win on strength and the verdict would flip to EVIDENCE_REFUTED. So
    this test fails the moment the gate stops being applied, which is the
    property the design calls for.
    """
    reviewed = _row(
        evidence_class=EvidenceClass.MUTAGENESIS,
        direction=Direction.SUPPORTS,
    )
    unreviewed = _row(
        evidence_class=EvidenceClass.FUNCTIONAL_ASSAY,
        direction=Direction.REFUTES,
        reviewed=False,
    )

    findings = check_evidence(None, [D294], [reviewed, unreviewed])
    codes = _codes(findings)

    assert "EVIDENCE_SUPPORTED" in codes
    assert "EVIDENCE_REFUTED" not in codes


def test_verdict_path_rejects_unreviewed_rows() -> None:
    """The verdict helper refuses unreviewed input instead of trusting callers.

    Defence in depth: the filter in :func:`check_evidence` is the policy, this
    is the invariant. A refactor that threads rows straight to the verdict
    raises rather than quietly grading unreviewed claims.
    """
    with pytest.raises(UnreviewedRowError, match="unreviewed"):
        verdict_findings([D294], [_row(reviewed=False)])


def test_unreviewed_rows_are_reported_even_though_excluded() -> None:
    """Excluded is not invisible. A curator needs to see there is work pending."""
    rows = [
        _row(reviewed=False),
        _row(residues=(H277,), reviewed=False),
        _row(residues=(Y346,), reviewed=False),  # not requested, not counted
    ]
    findings = check_evidence(None, [D294, H277], rows)

    present = [f for f in findings if f.code == "UNREVIEWED_EVIDENCE_PRESENT"]
    assert len(present) == 1
    assert present[0].key is None
    assert present[0].severity is Severity.WARN
    assert present[0].evidence["n_unreviewed"] == 2
    assert "did not affect" in present[0].message


def test_no_unreviewed_finding_when_table_is_fully_reviewed() -> None:
    findings = check_evidence(None, [D294], [_row()])
    assert "UNREVIEWED_EVIDENCE_PRESENT" not in _codes(findings)


# --------------------------------------------------------------------------
# Load-time validation: provenance is mandatory
# --------------------------------------------------------------------------


def test_missing_source_is_a_load_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: [C294]
    claim: the triad is catalytic
    evidence_class: ASSERTION
    direction: SUPPORTS
    reviewed: false
""",
    )
    with pytest.raises(EvidenceTableError) as exc:
        load_table(path)
    # The offending row must be identifiable from the message alone.
    assert "the triad is catalytic" in str(exc.value)
    assert "source" in str(exc.value)


def test_malformed_source_is_a_load_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: [C294]
    claim: as described by Smith and colleagues
    source: Smith et al. 2019
    evidence_class: ASSERTION
    direction: SUPPORTS
    reviewed: false
""",
    )
    with pytest.raises(EvidenceTableError) as exc:
        load_table(path)
    assert "as described by Smith and colleagues" in str(exc.value)
    assert "Smith et al. 2019" in str(exc.value)


def test_bare_number_is_not_accepted_as_a_pmid(tmp_path: Path) -> None:
    """A bare integer could be anything; we will not guess it is a PMID.

    Same policy as ``parse_hotspot_spec`` rejecting a chainless residue number.
    """
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: [C294]
    claim: bare number source
    source: 28270616
    evidence_class: ASSERTION
    direction: SUPPORTS
    reviewed: false
""",
    )
    with pytest.raises(EvidenceTableError, match="PMID:28270616"):
        load_table(path)


@pytest.mark.parametrize(
    "source",
    [
        "10.1073/pnas.1615695114",
        "doi:10.1073/pnas.1615695114",
        "https://doi.org/10.1128/JVI.00680-16",
        "PMID:28270616",
        "pmid: 28053231",
    ],
)
def test_accepted_source_shapes(tmp_path: Path, source: str) -> None:
    path = _write(
        tmp_path / "t.yaml",
        f"""
target: TEST
rows:
  - residues: [C294]
    claim: ok
    source: "{source}"
    evidence_class: ASSERTION
    direction: SUPPORTS
    reviewed: false
""",
    )
    assert len(load_table(path)) == 1


def test_reviewed_row_without_reviewer_is_a_load_error(tmp_path: Path) -> None:
    """``reviewed: true`` is an accountable act, so it needs a name on it."""
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: [C294]
    claim: accepted by nobody in particular
    source: PMID:28270616
    evidence_class: MUTAGENESIS
    direction: SUPPORTS
    reviewed: true
""",
    )
    with pytest.raises(EvidenceTableError) as exc:
        load_table(path)
    assert "reviewer" in str(exc.value)
    assert "accepted by nobody in particular" in str(exc.value)


def test_unknown_evidence_class_is_a_load_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: [C294]
    claim: vibes
    source: PMID:28270616
    evidence_class: GUT_FEELING
    direction: SUPPORTS
    reviewed: false
""",
    )
    with pytest.raises(EvidenceTableError, match="GUT_FEELING"):
        load_table(path)


def test_empty_residue_list_is_a_load_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.yaml",
        """
target: TEST
rows:
  - residues: []
    claim: about nothing
    source: PMID:28270616
    evidence_class: ASSERTION
    direction: SUPPORTS
    reviewed: false
""",
    )
    with pytest.raises(EvidenceTableError, match="residues"):
        load_table(path)


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(EvidenceTableError, match="nope.yaml"):
        load_table(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------
# Finding codes
# --------------------------------------------------------------------------


def test_evidence_refuted_fires_for_the_dwv_triad() -> None:
    """The case this module exists for.

    A paper asserts the residues form a catalytic triad; the only functional
    assay ever run on the homologous site was negative. The negative assay is
    the stronger evidence class and must decide the finding.
    """
    rows = [
        _row(
            residues=(H277, S278, D294),
            claim="side-chain arrangement indicates a catalytic triad",
            source="10.1073/pnas.1615695114",
            evidence_class=EvidenceClass.ASSERTION,
            direction=Direction.SUPPORTS,
        ),
        _row(
            residues=(H277, S278, D294),
            claim="lipase activity excluded against six lipid classes",
            source="10.1073/pnas.1616562114",
            evidence_class=EvidenceClass.FUNCTIONAL_ASSAY,
            direction=Direction.REFUTES,
        ),
    ]
    findings = check_evidence(None, [H277, S278, D294], rows)

    refuted = [f for f in findings if f.code == "EVIDENCE_REFUTED"]
    assert len(refuted) == 3
    assert {f.key for f in refuted} == {H277, S278, D294}
    for f in refuted:
        assert f.severity is Severity.WARN
        assert f.check == "evidence"
        # A reader must be able to go and read the refutation themselves.
        assert "10.1073/pnas.1616562114" in f.message
        assert "FUNCTIONAL_ASSAY" in f.message
    # The weaker supporting assertion must not also fire.
    assert "EVIDENCE_WEAK" not in _codes(findings)
    assert "EVIDENCE_SUPPORTED" not in _codes(findings)


def test_strongest_evidence_wins_over_assertion() -> None:
    """FUNCTIONAL_ASSAY outranks ASSERTION when both cover the same residue."""
    rows = [
        _row(evidence_class=EvidenceClass.ASSERTION, direction=Direction.SUPPORTS),
        _row(
            evidence_class=EvidenceClass.FUNCTIONAL_ASSAY,
            direction=Direction.SUPPORTS,
            source="PMID:28053231",
        ),
    ]
    findings = check_evidence(None, [D294], rows)
    assert _codes(findings) == ["EVIDENCE_SUPPORTED"]
    assert findings[0].severity is Severity.PASS
    assert findings[0].evidence["evidence_class"] == "FUNCTIONAL_ASSAY"


def test_evidence_weak_for_assertion_only_residue() -> None:
    findings = check_evidence(None, [D294], [_row()])
    assert _codes(findings) == ["EVIDENCE_WEAK"]
    weak = findings[0]
    assert weak.severity is Severity.WARN
    # The message has to say why an assertion is not enough.
    assert "not an assayed result" in weak.message
    assert "10.1073/pnas.1615695114" in weak.message


def test_evidence_weak_for_conservation_only_residue() -> None:
    findings = check_evidence(
        None, [D294], [_row(evidence_class=EvidenceClass.CONSERVATION)]
    )
    assert _codes(findings) == ["EVIDENCE_WEAK"]


def test_evidence_supported_for_mutagenesis() -> None:
    findings = check_evidence(
        None, [D294], [_row(evidence_class=EvidenceClass.MUTAGENESIS)]
    )
    assert _codes(findings) == ["EVIDENCE_SUPPORTED"]
    assert findings[0].severity is Severity.PASS


def test_no_evidence_is_site_level_and_emitted_once() -> None:
    """Three uncovered residues, one finding — not three copies of the same news."""
    findings = check_evidence(None, [H277, S278, D294], [])
    no_ev = [f for f in findings if f.code == "NO_EVIDENCE"]
    assert len(no_ev) == 1
    assert no_ev[0].key is None
    assert no_ev[0].severity is Severity.WARN
    assert no_ev[0].evidence["n_requested"] == 3
    # Absence of evidence is not evidence of absence, and the message says so.
    assert "not evidence of absence" in no_ev[0].message


def test_no_evidence_suppressed_when_any_residue_is_covered() -> None:
    findings = check_evidence(None, [D294, Y346], [_row()])
    assert "NO_EVIDENCE" not in _codes(findings)


def test_uncovered_residue_emits_nothing_of_its_own() -> None:
    """Silence per residue; the site-level finding carries the coverage story.

    Emitting a per-residue "no evidence" code would let an empty table flood a
    report with warnings that all say the same thing.
    """
    findings = check_evidence(None, [D294, Y346], [_row()])
    assert [f.key for f in findings] == [D294]


def test_findings_are_sorted() -> None:
    rows = [
        _row(residues=(D294,), evidence_class=EvidenceClass.MUTAGENESIS),
        _row(residues=(H277,), evidence_class=EvidenceClass.MUTAGENESIS),
        _row(residues=(S278,), reviewed=False),
    ]
    findings = check_evidence(None, [D294, H277, S278], rows)
    # Residue order first (277, 294), then the site-level finding last.
    assert [f.key for f in findings] == [H277, D294, None]


def test_check_emits_no_structural_codes() -> None:
    """Evidence never adjudicates geometry; that is someone else's check."""
    structural = {"UNMODELLED", "BURIED", "NO_SUCH_CHAIN", "NOT_DECLARED"}
    rows = [_row(), _row(residues=(H277,), reviewed=False)]
    findings = check_evidence(None, [D294, H277, Y346], rows)
    assert structural.isdisjoint(_codes(findings))
    assert all(f.check == "evidence" for f in findings)


def test_no_findings_at_all_when_no_residues_requested() -> None:
    assert check_evidence(None, [], [_row()]) == []


# --------------------------------------------------------------------------
# rows_for and ordering
# --------------------------------------------------------------------------


def test_rows_for_matches_any_residue_in_the_row() -> None:
    row = _row(residues=(H277, S278, D294))
    other = _row(residues=(Y346,))
    assert rows_for([row, other], S278) == [row]
    assert rows_for([row, other], Y346) == [other]
    assert rows_for([row, other], ResidueKey("C", 999)) == []


def test_evidence_class_strength_is_ordered_strongest_first() -> None:
    order = [
        EvidenceClass.FUNCTIONAL_ASSAY,
        EvidenceClass.MUTAGENESIS,
        EvidenceClass.STRUCTURAL_OBSERVATION,
        EvidenceClass.CONSERVATION,
        EvidenceClass.ASSERTION,
    ]
    strengths = [c.strength for c in order]
    assert strengths == sorted(strengths, reverse=True)
    assert len(set(strengths)) == len(strengths)


# --------------------------------------------------------------------------
# The shipped table
# --------------------------------------------------------------------------


def test_shipped_dwv_table_loads() -> None:
    rows = load_table(BUNDLED_TABLE_DIR / "dwv_6f5j.yaml")
    assert rows, "the shipped table must not be empty"
    for row in rows:
        assert row.residues
        assert row.claim
        assert row.source
        if row.reviewed:
            assert row.reviewer


def test_shipped_dwv_table_refutes_the_triad() -> None:
    """The regression test for our own worst mistake.

    We targeted this site and ordered designs against it. If a future edit to
    the table ever lets the triad read as supported, this fails.
    """
    rows = load_table(BUNDLED_TABLE_DIR / "dwv_6f5j.yaml")
    findings = check_evidence(None, [H277, S278, D294], rows)
    assert set(_codes(findings)) <= {"EVIDENCE_REFUTED", "UNREVIEWED_EVIDENCE_PRESENT"}
    assert _codes(findings).count("EVIDENCE_REFUTED") == 3


# --------------------------------------------------------------------------
# Grader
# --------------------------------------------------------------------------


def _grounded_example():
    # Synthetic fixture, not a claim about the real cited publication.
    text = "Synthetic test: mutation of D294 had no effect."
    sources = [{"source": "PMID:28270616", "text": text}]
    row = {"residues": ["C294"], "claim": text, "quote": text,
           "source": sources[0]["source"], "span_start": 0, "span_end": len(text),
           "evidence_class": "MUTAGENESIS", "direction": "REFUTES",
           "reviewed": True, "reviewer": "model"}
    return sources, row


@pytest.mark.parametrize("change", [
    {"source": "PMID:123"},
    {"quote": "a fabricated result"},
    {"span_end": 999},
    {"claim": "stronger than the source"},
    {"residues": ["C277"]},
])
def test_grader_rejects_unsupported_source_spans(change):
    from hotspot_preflight.evidence.grader import draft
    sources, row = _grounded_example()
    row.update(change)
    result = draft("synthetic target", [D294], sources=sources,
                   complete=lambda _: json.dumps([row]))
    assert not result.rows
    assert result.n_dropped == 1


def test_grounded_model_draft_cannot_self_approve_or_affect_verdict(tmp_path):
    from hotspot_preflight.evidence.grader import draft_rows, write_drafts
    sources, row = _grounded_example()
    rows = draft_rows("synthetic target", [D294], sources=sources,
                      complete=lambda _: json.dumps([row]))
    assert rows[0].reviewed is False
    assert rows[0].reviewer == ""
    assert rows[0].claim == sources[0]["text"]
    output = write_drafts(rows, tmp_path / "draft.yaml", target="synthetic")
    reloaded = load_table(output)
    assert _codes(check_evidence(None, [D294], reloaded)) == [
        "NO_EVIDENCE", "UNREVIEWED_EVIDENCE_PRESENT"]


def test_grader_requires_sources_before_calling_model():
    from hotspot_preflight.evidence.grader import draft
    called = []
    with pytest.raises(EvidenceTableError):
        draft("synthetic", [D294], complete=lambda _: called.append(True))
    assert called == []


def test_remote_grader_requires_explicit_opt_in(monkeypatch):
    from hotspot_preflight.evidence.grader import draft, GraderUnavailable
    sources, _ = _grounded_example()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-never-transmitted")
    with pytest.raises(GraderUnavailable, match="allow_remote"):
        draft("synthetic", [D294], sources=sources)


def test_grader_rejects_unparseable_response():
    from hotspot_preflight.evidence.grader import draft, GraderResponseError
    sources, _ = _grounded_example()
    with pytest.raises(GraderResponseError):
        draft("synthetic", [D294], sources=sources, complete=lambda _: "not JSON")


@pytest.mark.parametrize("mention", ["C1294", "C2940"])
def test_grounded_draft_rejects_residue_number_substrings(mention):
    from hotspot_preflight.evidence.grader import draft
    text = f"Synthetic mutation of {mention} had no effect."
    sources = [{"source": "PMID:123", "text": text}]
    row = {"residues": ["C294"], "claim": text, "quote": text, "source": "PMID:123",
           "span_start": 0, "span_end": len(text), "evidence_class": "MUTAGENESIS",
           "direction": "REFUTES"}
    result = draft("synthetic", [D294], sources=sources, complete=lambda _: json.dumps([row]))
    assert result.rows == ()
    assert result.n_dropped == 1


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None])
def test_review_gate_rejects_nonboolean_flags(flag):
    sources, row = _grounded_example()
    row["reviewed"] = flag
    with pytest.raises(EvidenceTableError, match="boolean"):
        row_from_mapping(row)


# --------------------------------------------------------------------------
# No network at import
# --------------------------------------------------------------------------


def test_no_network_call_at_import(monkeypatch) -> None:
    """Importing the evidence layer must never touch the network.

    A module that builds an API client at import time makes the entire CLI
    unusable offline and leaks a key requirement into unrelated commands.
    """

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("evidence module opened a socket at import time")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)

    for name in (
        "hotspot_preflight.evidence",
        "hotspot_preflight.evidence.table",
        "hotspot_preflight.evidence.grader",
    ):
        importlib.reload(importlib.import_module(name))
