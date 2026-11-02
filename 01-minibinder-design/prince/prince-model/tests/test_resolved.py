# SPDX-License-Identifier: MIT
"""Tests for the resolved-residue check.

The synthetic fixtures use author numbering = label_seq + 100, so a test that
passes here cannot be passing because the two numbering schemes coincide.

Two fixtures carry the same gap (author 104 and 105 declared, unmodelled) and
differ only in whether the entry declares it via
``_pdbx_unobs_or_zero_occ_residues``. Every assertion about detection is made
against both, because an entry omitting that optional category must still be
checked correctly rather than reported clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hotspot_preflight.checks.resolved import CHECK_NAME, check_resolved
from hotspot_preflight.findings import (
    Severity,
    SiteReport,
    finding_sort_key,
    sort_findings,
)
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import load_target

EXISTENCE_CODES = {"UNMODELLED", "NOT_DECLARED", "NO_SUCH_CHAIN", "RESOLVED"}


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def only(findings, code):
    """The single finding with this code, asserting there is exactly one."""
    matches = [f for f in findings if f.code == code]
    assert len(matches) == 1, f"expected one {code}, got {codes(findings)}"
    return matches[0]


def residue_findings(findings, key):
    return [f for f in findings if f.key == key]


# --------------------------------------------------------------------------
# The core verdicts, on the entry that declares its own gap.
# --------------------------------------------------------------------------


def test_unmodelled_residue_is_killed(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("A", 104)])

    f = only(findings, "UNMODELLED")
    assert f.severity is Severity.KILL
    assert f.check == CHECK_NAME
    assert f.key == ResidueKey("A", 104)
    # The message has to say what is wrong and in which entry, because it is
    # read out of a log with no other context.
    assert "never observed" in f.message.lower()
    assert "TEST" in f.message


def test_unmodelled_evidence_records_both_detection_routes(cif_with_unobs_category):
    """A reader must be able to see that the two routes agreed."""
    target = load_target(cif_with_unobs_category)
    f = only(check_resolved(target, [ResidueKey("A", 104)]), "UNMODELLED")

    assert f.evidence["in_unobs_category"] is True
    assert f.evidence["in_derived_gap"] is True
    assert f.evidence["entry_id"] == "TEST"


def test_observed_residue_passes(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("A", 101)])

    f = only(findings, "RESOLVED")
    assert f.severity is Severity.PASS
    assert findings == [f], "a clean residue should produce nothing else"


def test_undeclared_number_is_killed_and_shows_the_real_range(
    cif_with_unobs_category,
):
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("A", 999)])

    f = only(findings, "NOT_DECLARED")
    assert f.severity is Severity.KILL
    # The actionable diagnosis: you have the wrong chain or a typo.
    assert "typo" in f.message.lower() or "wrong chain" in f.message.lower()
    assert f.evidence["declared_min"] == 101
    assert f.evidence["declared_max"] == 106
    assert "101" in f.message and "106" in f.message


def test_unknown_chain_is_killed_and_lists_the_real_chains(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("Z", 101)])

    f = only(findings, "NO_SUCH_CHAIN")
    assert f.severity is Severity.KILL
    assert f.evidence["chains_present"] == ["A"]
    assert "A" in f.message


def test_unknown_chain_suppresses_the_not_declared_verdict(cif_with_unobs_category):
    """A bad chain makes the residue number meaningless; reporting both is noise."""
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("Z", 999)])

    assert codes(findings) == ["NO_SUCH_CHAIN"]


def test_wrong_case_chain_says_so_explicitly(cif_with_unobs_category):
    """Case is the most common and most easily fixed chain-id mistake."""
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("a", 101)])

    f = only(findings, "NO_SUCH_CHAIN")
    assert f.severity is Severity.KILL
    assert "case" in f.message.lower()
    assert f.evidence["case_insensitive_matches"] == ["A"]


def test_case_match_is_not_claimed_when_there_is_none(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    f = only(check_resolved(target, [ResidueKey("Z", 101)]), "NO_SUCH_CHAIN")

    assert f.evidence["case_insensitive_matches"] == []
    assert "case" not in f.message.lower()


# --------------------------------------------------------------------------
# Occupancy.
# --------------------------------------------------------------------------


def test_zero_occupancy_residue_warns(cif_with_zero_occupancy):
    """Atoms present but at zero occupancy means it was not really resolved."""
    target = load_target(cif_with_zero_occupancy)
    findings = check_resolved(target, [ResidueKey("A", 103)])

    f = only(findings, "LOW_OCCUPANCY")
    assert f.severity is Severity.WARN
    assert f.evidence["occupancy"] == pytest.approx(0.0)
    assert f.evidence["threshold"] == pytest.approx(0.5)


def test_zero_occupancy_residue_is_not_killed(cif_with_zero_occupancy):
    """It exists in the coordinates, so the existence verdict is not a kill."""
    target = load_target(cif_with_zero_occupancy)
    findings = residue_findings(
        check_resolved(target, [ResidueKey("A", 103)]), ResidueKey("A", 103)
    )

    assert "UNMODELLED" not in codes(findings)
    report = SiteReport(list(findings))
    assert report.kills == []


def test_full_occupancy_residue_gets_no_occupancy_warning(cif_with_zero_occupancy):
    target = load_target(cif_with_zero_occupancy)
    findings = check_resolved(target, [ResidueKey("A", 101)])

    assert "LOW_OCCUPANCY" not in codes(findings)


# --------------------------------------------------------------------------
# The None-versus-empty-set distinction. This is the whole point of the check.
# --------------------------------------------------------------------------


def test_missing_category_still_detects_the_gap(cif_without_unobs_category):
    """Code that trusts the optional category alone reports this entry clean."""
    target = load_target(cif_without_unobs_category)
    findings = check_resolved(target, [ResidueKey("A", 104)])

    assert only(findings, "UNMODELLED").severity is Severity.KILL


def test_missing_category_emits_exactly_one_site_level_warning(
    cif_without_unobs_category,
):
    target = load_target(cif_without_unobs_category)
    keys = [ResidueKey("A", n) for n in (101, 102, 104, 105)]
    findings = check_resolved(target, keys)

    f = only(findings, "NO_UNOBS_CATEGORY")
    assert f.severity is Severity.WARN
    assert f.key is None, "this is a statement about the entry, not a residue"
    assert "confidence" in f.message.lower()
    assert f.evidence["route_used"] == "alignment"


def test_missing_category_evidence_distinguishes_absent_from_empty(
    cif_without_unobs_category,
):
    """`None` records missing annotation; an empty set records an explicit empty category."""
    target = load_target(cif_without_unobs_category)
    f = only(check_resolved(target, []), "NO_UNOBS_CATEGORY")

    assert f.evidence["unobs_category_present"] is False


def test_present_category_does_not_emit_the_site_warning(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    findings = check_resolved(target, [ResidueKey("A", 104), ResidueKey("A", 101)])

    assert "NO_UNOBS_CATEGORY" not in codes(findings)


def test_unmodelled_evidence_marks_the_category_as_unknown_when_absent(
    cif_without_unobs_category,
):
    """Not False — the entry made no statement either way."""
    target = load_target(cif_without_unobs_category)
    f = only(check_resolved(target, [ResidueKey("A", 104)]), "UNMODELLED")

    assert f.evidence["in_unobs_category"] is None
    assert f.evidence["in_derived_gap"] is True


def test_routes_agreeing_produces_no_disagreement_warning(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    keys = [ResidueKey("A", n) for n in (101, 102, 103, 104, 105, 106)]
    findings = check_resolved(target, keys)

    assert "DETECTION_ROUTES_DISAGREE" not in codes(findings)


def test_absent_category_is_never_reported_as_disagreement(
    cif_without_unobs_category,
):
    """Silence is not disagreement. Only a present category can contradict."""
    target = load_target(cif_without_unobs_category)
    keys = [ResidueKey("A", n) for n in (101, 104, 105)]
    findings = check_resolved(target, keys)

    assert "DETECTION_ROUTES_DISAGREE" not in codes(findings)


def _with_bogus_unobs_claims(source: Path, tmp_path: Path) -> Path:
    """An entry whose category claims residue 101 is unobserved, though it has atoms.

    No shared fixture is internally inconsistent, and real inconsistent entries
    are rare, so the disagreement path would otherwise never be executed. The
    claim is appended to an entry that has no category rather than editing one,
    so the only difference from the clean case is the contradiction itself.
    """
    loop = """#
loop_
_pdbx_unobs_or_zero_occ_residues.id
_pdbx_unobs_or_zero_occ_residues.PDB_model_num
_pdbx_unobs_or_zero_occ_residues.polymer_flag
_pdbx_unobs_or_zero_occ_residues.occupancy_flag
_pdbx_unobs_or_zero_occ_residues.auth_asym_id
_pdbx_unobs_or_zero_occ_residues.auth_comp_id
_pdbx_unobs_or_zero_occ_residues.auth_seq_id
_pdbx_unobs_or_zero_occ_residues.PDB_ins_code
1 1 Y 1 A GLY 101 ?
#
"""
    out = tmp_path / "inconsistent.cif"
    out.write_text(source.read_text() + loop)
    return out


def test_false_unobserved_claim_warns_but_believes_the_coordinates(
    cif_without_unobs_category, tmp_path
):
    """Atoms exist, so the residue is RESOLVED; the bad annotation is a warning."""
    path = _with_bogus_unobs_claims(cif_without_unobs_category, tmp_path)
    findings = check_resolved(load_target(path), [ResidueKey("A", 101)])

    assert only(findings, "RESOLVED").severity is Severity.PASS
    f = only(findings, "DETECTION_ROUTES_DISAGREE")
    assert f.severity is Severity.WARN
    assert f.evidence["in_unobs_category"] is True
    assert f.evidence["in_derived_gap"] is False
    assert "inconsistent" in f.message.lower()


def test_gap_the_category_omits_is_still_killed_and_flagged(
    cif_without_unobs_category, tmp_path
):
    """The category exists but misses 104. The derived route must still kill it."""
    path = _with_bogus_unobs_claims(cif_without_unobs_category, tmp_path)
    findings = check_resolved(load_target(path), [ResidueKey("A", 104)])

    assert only(findings, "UNMODELLED").severity is Severity.KILL
    f = only(findings, "DETECTION_ROUTES_DISAGREE")
    assert f.evidence["in_unobs_category"] is False
    assert f.evidence["in_derived_gap"] is True
    # The category is present, merely wrong, so confidence is not downgraded.
    assert "NO_UNOBS_CATEGORY" not in codes(findings)


# --------------------------------------------------------------------------
# Invariants that hold for every input.
# --------------------------------------------------------------------------


def test_exactly_one_existence_verdict_per_residue(cif_without_unobs_category):
    target = load_target(cif_without_unobs_category)
    keys = [
        ResidueKey("A", 101),
        ResidueKey("A", 104),
        ResidueKey("A", 999),
        ResidueKey("Z", 101),
    ]
    findings = check_resolved(target, keys)

    for key in keys:
        got = [f.code for f in findings if f.key == key and f.code in EXISTENCE_CODES]
        assert len(got) == 1, f"{key} got {got}"


def test_no_burial_verdict_is_emitted(cif_with_unobs_category):
    """Exposure is the burial check's job; two checks owning it would conflict."""
    target = load_target(cif_with_unobs_category)
    keys = [ResidueKey("A", n) for n in (101, 104)]
    findings = check_resolved(target, keys)

    for f in findings:
        assert f.check == CHECK_NAME
        assert "BURIED" not in f.code and "SASA" not in f.code


def test_caller_order_is_preserved(cif_without_unobs_category):
    """The order a user writes hotspots in sometimes reflects priority.

    `parse_hotspot_spec` preserves first-seen order for that reason, so a check
    that sorted internally would silently discard it. Presentation order is the
    aggregator's job, via `sort_findings`.
    """
    target = load_target(cif_without_unobs_category)
    asked = [ResidueKey("A", 106), ResidueKey("A", 101), ResidueKey("A", 104)]
    findings = check_resolved(target, asked)
    residue_keys = [f.key for f in findings if f.key is not None]

    assert residue_keys == asked, "findings must come back in the order asked"


def test_caller_order_survives_multiple_findings_for_one_residue(
    cif_with_zero_occupancy,
):
    """A residue with two findings must not break the caller's sequence."""
    target = load_target(cif_with_zero_occupancy)
    asked = [ResidueKey("A", 104), ResidueKey("A", 103), ResidueKey("A", 101)]
    findings = check_resolved(target, asked)
    seen: list[ResidueKey] = []
    for f in findings:
        if f.key is not None and f.key not in seen:
            seen.append(f.key)

    assert seen == asked
    # 103 is the zero-occupancy residue: both of its findings stay together.
    assert codes(residue_findings(findings, ResidueKey("A", 103))) == [
        "RESOLVED",
        "LOW_OCCUPANCY",
    ]


def test_site_level_findings_come_last(cif_without_unobs_category):
    target = load_target(cif_without_unobs_category)
    keys = [ResidueKey("A", 104), ResidueKey("A", 101)]
    findings = check_resolved(target, keys)

    assert findings[-1].key is None
    assert all(f.key is not None for f in findings[:-1])


def test_canonical_order_is_available_through_sort_findings(
    cif_without_unobs_category,
):
    """The aggregator's ordering is total and puts site-level findings last."""
    target = load_target(cif_without_unobs_category)
    scrambled = [
        ResidueKey("A", 106),
        ResidueKey("Z", 5),
        ResidueKey("A", 104),
        ResidueKey("A", 101),
    ]
    ordered = sort_findings(check_resolved(target, scrambled))
    sort_keys = [finding_sort_key(f) for f in ordered]

    assert sort_keys == sorted(sort_keys)
    assert [f.key for f in ordered if f.key is not None] == sorted(
        scrambled, key=lambda k: (k.auth_asym_id, k.auth_seq_id, k.icode)
    )
    assert ordered[-1].key is None


def test_canonical_order_is_stable_across_input_permutations(
    cif_without_unobs_category,
):
    """Caller order varies; the sorted run record must not."""
    target = load_target(cif_without_unobs_category)
    forward = [ResidueKey("A", 101), ResidueKey("A", 104), ResidueKey("A", 106)]
    backward = list(reversed(forward))

    assert sort_findings(check_resolved(target, forward)) == sort_findings(
        check_resolved(target, backward)
    )


def test_empty_key_list_on_a_clean_entry_produces_no_findings(
    cif_with_unobs_category,
):
    target = load_target(cif_with_unobs_category)

    assert check_resolved(target, []) == []


# --------------------------------------------------------------------------
# A chain whose numbering cannot be reconciled.
# --------------------------------------------------------------------------


def _cif_with_irregular_numbering(tmp_path: Path) -> Path:
    """An entry whose label-to-author offset is not a single constant.

    `structure._declared_by_offset` names unmodelled residues by finding the
    constant label->author shift a chain implies. When mid-chain renumbering
    makes that shift non-constant, it omits the chain rather than inventing
    numbers — so nothing on that chain is declared, in author numbering, even
    though the chain is plainly present in the coordinates.

    No shared fixture reaches this, which is why it was found by mutation rather
    than by a failing test: a mutation that gutted the branch handling it passed
    all 38 tests. Built here with gemmi, the same way `conftest.py` builds its
    fixtures, so it exercises the real parse path.
    """
    import gemmi

    st = gemmi.Structure()
    st.name = "IRREG"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    # Offsets 100 and 103: label 1 -> author 101, label 2 -> author 105.
    for label_seq, auth_seq, comp in [(1, 101, "GLY"), (2, 105, "ALA")]:
        res = gemmi.Residue()
        res.name = comp
        res.seqid = gemmi.SeqId(auth_seq, " ")
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
    for entity in st.entities:
        if entity.entity_type == gemmi.EntityType.Polymer:
            entity.full_sequence = ["GLY", "ALA", "VAL"]

    path = tmp_path / "irregular.cif"
    path.write_text(st.make_mmcif_document().as_string())
    return path


def test_irreconcilable_numbering_does_not_blame_the_user(tmp_path):
    """The message must not say "typo" when the entry is the problem.

    A residue on such a chain may well be declared; we simply cannot say which
    author number it carries. Reporting a typo would send the user looking for a
    mistake they did not make.
    """
    target = load_target(_cif_with_irregular_numbering(tmp_path))
    findings = check_resolved(target, [ResidueKey("A", 101)])

    f = only(findings, "NOT_DECLARED")
    assert f.severity is Severity.KILL
    assert "could not be reconciled" in f.message
    assert "typo" not in f.message.lower()
    assert "property of the entry" in f.message


def test_irreconcilable_numbering_reports_an_empty_declared_range(tmp_path):
    """Evidence must say there is no range rather than inventing one."""
    target = load_target(_cif_with_irregular_numbering(tmp_path))
    f = only(
        check_resolved(target, [ResidueKey("A", 101)]),
        "NOT_DECLARED",
    )

    assert f.evidence["declared_min"] is None
    assert f.evidence["declared_max"] is None
    assert f.evidence["n_declared"] == 0


def test_irreconcilable_numbering_still_rejects_a_bad_chain_first(tmp_path):
    """Chain precedence holds even when the chain that exists is unusable."""
    target = load_target(_cif_with_irregular_numbering(tmp_path))
    findings = check_resolved(target, [ResidueKey("Q", 101)])
    residue_codes = [f.code for f in findings if f.key is not None]

    assert residue_codes == ["NO_SUCH_CHAIN"]


# --------------------------------------------------------------------------
# The evidence shape is a cross-module contract.
# --------------------------------------------------------------------------

#: Exact ``evidence`` keys each code carries. Pinned deliberately, and pinned
#: *here* rather than in the consumer's tests: `report.py` and the HTML report
#: read these keys by name, so renaming or dropping one is a breaking change
#: that should fail in this module's own suite, where the edit was made, rather
#: than surfacing as a KeyError in somebody else's. Changing a set here is
#: allowed — it just has to be a decision, not a side effect.
EVIDENCE_CONTRACT = {
    "NO_SUCH_CHAIN": {"chains_present", "case_insensitive_matches", "entry_id"},
    "NOT_DECLARED": {"declared_min", "declared_max", "n_declared", "entry_id"},
    "UNMODELLED": {
        "in_unobs_category",
        "in_derived_gap",
        "unobs_category_present",
        "entry_id",
    },
    "RESOLVED": {"occupancy", "entry_id"},
    "LOW_OCCUPANCY": {"occupancy", "threshold", "entry_id"},
    "DETECTION_ROUTES_DISAGREE": {
        "in_unobs_category",
        "in_derived_gap",
        "unobs_category_present",
        "entry_id",
    },
    "NO_UNOBS_CATEGORY": {
        "unobs_category_present",
        "route_used",
        "n_derived_unobserved",
        "entry_id",
    },
}


def _findings_covering_every_code(
    cif_with_unobs_category: Path,
    cif_without_unobs_category: Path,
    cif_with_zero_occupancy: Path,
    tmp_path: Path,
) -> list:
    """Findings spanning all seven codes, gathered from four entries.

    One entry cannot produce all seven: the site-level warning needs an entry
    without the category, the disagreement needs an inconsistent one, and the
    occupancy warning needs the zero-occupancy one.
    """
    inconsistent = _with_bogus_unobs_claims(cif_without_unobs_category, tmp_path)
    cases = [
        (
            cif_with_unobs_category,
            [ResidueKey("A", 101), ResidueKey("A", 104), ResidueKey("A", 999),
             ResidueKey("Z", 1)],
        ),
        (cif_without_unobs_category, [ResidueKey("A", 104)]),
        (cif_with_zero_occupancy, [ResidueKey("A", 103)]),
        (inconsistent, [ResidueKey("A", 101)]),
    ]
    out = []
    for path, keys in cases:
        out.extend(check_resolved(load_target(path), keys))
    return out


def test_evidence_keys_match_the_cross_module_contract(
    cif_with_unobs_category,
    cif_without_unobs_category,
    cif_with_zero_occupancy,
    tmp_path,
):
    findings = _findings_covering_every_code(
        cif_with_unobs_category,
        cif_without_unobs_category,
        cif_with_zero_occupancy,
        tmp_path,
    )

    for f in findings:
        assert set(f.evidence) == EVIDENCE_CONTRACT[f.code], (
            f"{f.code} evidence keys drifted: "
            f"got {sorted(f.evidence)}, "
            f"expected {sorted(EVIDENCE_CONTRACT[f.code])}"
        )


def test_the_evidence_contract_is_exercised_for_every_code(
    cif_with_unobs_category,
    cif_without_unobs_category,
    cif_with_zero_occupancy,
    tmp_path,
):
    """Without this, the contract test passes vacuously on codes never emitted.

    A key set that no fixture reaches is not pinned by anything, so the set of
    codes observed must equal the set of codes declared.
    """
    findings = _findings_covering_every_code(
        cif_with_unobs_category,
        cif_without_unobs_category,
        cif_with_zero_occupancy,
        tmp_path,
    )

    assert {f.code for f in findings} == set(EVIDENCE_CONTRACT)


def test_every_code_in_the_contract_is_a_known_code():
    """The contract must not outlive a code that was removed from the check."""
    assert set(EVIDENCE_CONTRACT) >= set(EXISTENCE_CODES)
    assert set(EVIDENCE_CONTRACT) == set(EXISTENCE_CODES) | {
        "LOW_OCCUPANCY",
        "DETECTION_ROUTES_DISAGREE",
        "NO_UNOBS_CATEGORY",
    }


def test_entry_id_is_on_every_finding(
    cif_with_unobs_category,
    cif_without_unobs_category,
    cif_with_zero_occupancy,
    tmp_path,
):
    """Findings are read out of logs with no other context; name the entry."""
    findings = _findings_covering_every_code(
        cif_with_unobs_category,
        cif_without_unobs_category,
        cif_with_zero_occupancy,
        tmp_path,
    )

    for f in findings:
        assert f.evidence["entry_id"] == "TEST"


# --------------------------------------------------------------------------
# The real entry this project exists because of.
# --------------------------------------------------------------------------


@pytest.mark.network
def test_6f5j_catches_the_two_hotspots_the_campaign_actually_used(real_6f5j):
    """Ile405 and Phe408 on chain C: 35 designs ordered, 1 bound."""
    target = load_target(real_6f5j)
    keys = [ResidueKey("C", 405), ResidueKey("C", 408)]
    findings = check_resolved(target, keys)

    for key in keys:
        f = only(residue_findings(findings, key), "UNMODELLED")
        assert f.severity is Severity.KILL
    assert SiteReport(findings).verdict.value == "STOP"


@pytest.mark.network
def test_6f5j_preserves_a_deliberately_unsorted_hotspot_list(real_6f5j):
    """A real target, asked for in priority order rather than numeric order."""
    target = load_target(real_6f5j)
    asked = [ResidueKey("C", 408), ResidueKey("C", 300), ResidueKey("C", 405)]
    findings = check_resolved(target, asked)

    assert [f.key for f in findings] == asked
    assert codes(findings) == ["UNMODELLED", "RESOLVED", "UNMODELLED"]


@pytest.mark.network
def test_6f5j_passes_a_residue_that_is_actually_modelled(real_6f5j):
    target = load_target(real_6f5j)
    findings = check_resolved(target, [ResidueKey("C", 300)])

    assert only(findings, "RESOLVED").severity is Severity.PASS


@pytest.mark.network
def test_6f5j_flags_the_whole_unmodelled_tail(real_6f5j):
    """Chain C declares 416 residues; 399-416 have no coordinates at all."""
    target = load_target(real_6f5j)
    keys = [ResidueKey("C", n) for n in range(399, 417)]
    findings = check_resolved(target, keys)
    killed = [f for f in findings if f.code == "UNMODELLED"]

    assert len(keys) == 18
    assert sorted(f.key for f in killed) == sorted(keys)


@pytest.mark.network
def test_6f5j_routes_agree(real_6f5j):
    """A curated entry should be internally consistent; if it stops being, say so."""
    target = load_target(real_6f5j)
    keys = [ResidueKey("C", n) for n in range(395, 417)]
    findings = check_resolved(target, keys)

    assert "DETECTION_ROUTES_DISAGREE" not in codes(findings)
    assert "NO_UNOBS_CATEGORY" not in codes(findings)


@pytest.mark.network
def test_6f5j_rejects_a_lowercase_chain_id(real_6f5j):
    target = load_target(real_6f5j)
    f = only(check_resolved(target, [ResidueKey("c", 300)]), "NO_SUCH_CHAIN")

    assert "case" in f.message.lower()
    assert f.evidence["case_insensitive_matches"] == ["C"]
