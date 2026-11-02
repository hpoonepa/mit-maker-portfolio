# SPDX-License-Identifier: MIT
"""Tests for the burial check.

The realistic fixture is **1TIM**, triosephosphate isomerase from chicken. It
was chosen because it is an obligate homodimer whose interface is not a flat
patch but an interdigitated one: "loop 3" (residues 70-80) of each subunit
inserts into the active site of its partner. That gives residues whose solvent
accessibility differs by almost the full dynamic range between the isolated
chain and the dimer -- Thr75 is 0.95 exposed alone and 0.002 in the dimer -- so
a check that silently used the wrong context cannot pass by coincidence. It is
also small (2 chains, 3740 atoms) and its deposited assembly is exactly the
dimer, so no symmetry reasoning is needed to get the biological form.

6F5J is used for one test only: it expands to 180 chains, which is the case the
neighbourhood trim exists for.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import gemmi
import pytest

from hotspot_preflight.checks.burial import (
    BURIED_RELATIVE_SASA,
    CROP_ARTIFACT_DELTA,
    NEIGHBOUR_CUTOFF_A,
    PUBLISHED_MAX_SASA,
    REQUIRED_PARAMETER_KEYS,
    SASA_PROBE_RADIUS,
    BurialProfile,
    _neighbour_search,
    check_burial,
    compare_contexts,
    reference_digest,
    compute_burial,
    expand_assembly,
    reference_max_sasa,
    trim_to_neighbourhood,
)
from hotspot_preflight.checks import sasa as sasa_module
from hotspot_preflight.checks.assembly import _restore_author_chain_names
from hotspot_preflight.findings import Severity, sort_findings
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import load_target

CACHE = Path(__file__).resolve().parents[1] / ".cache"

# Chain A of 1TIM. Values measured with this module's own parameters.
TIM_INTERIOR = ResidueKey("A", 7)  # PHE, 0.000 on the dimer -- true core
TIM_INTERFACE = ResidueKey("A", 75)  # THR, 0.948 alone / 0.002 in the dimer
TIM_INTERFACE_2 = ResidueKey("A", 14)  # MET, 0.866 alone / 0.001 in the dimer
TIM_EXPOSED = ResidueKey("A", 36)  # ASP, 0.76 in the dimer, no partner effect
TIM_CUT_FACE = ResidueKey("A", 90)  # TRP, 1.04 on the 70-90 crop / 0.11 dimer
TIM_CROP = ("A", 70, 90)


@pytest.fixture(scope="session")
def real_1tim() -> Path:
    """Download 1TIM once into .cache/, skipping when offline."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "1tim_updated.cif"
    if not path.exists():  # pragma: no cover - network path
        url = "https://www.ebi.ac.uk/pdbe/entry-files/download/1tim_updated.cif"
        try:
            urllib.request.urlretrieve(url, path)
        except (urllib.error.URLError, OSError) as exc:
            pytest.skip(f"cannot download 1TIM: {exc}")
    return path


@pytest.fixture(scope="session")
def tim_findings(real_1tim: Path) -> list:
    """One shared run over every anchor residue, with the crop applied.

    Session-scoped because each run does three SASA passes; the tests below
    only interrogate different parts of the same answer.
    """
    target = load_target(real_1tim)
    keys = [
        TIM_INTERIOR,
        TIM_INTERFACE,
        TIM_INTERFACE_2,
        TIM_EXPOSED,
        TIM_CUT_FACE,
        ResidueKey("A", 70),
    ]
    return check_burial(target, keys, crop_range=TIM_CROP)


def codes_for(findings, key: ResidueKey) -> set[str]:
    return {f.code for f in findings if f.key == key}


def finding(findings, key: ResidueKey, code: str):
    matches = [f for f in findings if f.key == key and f.code == code]
    assert matches, f"no {code} for {key}; got {sorted(codes_for(findings, key))}"
    return matches[0]


# --------------------------------------------------------------------------
# Deterministic tests on the synthetic fixtures
# --------------------------------------------------------------------------


def test_no_assembly_defined_is_reported_not_assumed(cif_with_unobs_category):
    """The synthetic entry declares no assembly, so we must say so.

    Treating the asymmetric unit as the assembly would be the silent-wrong
    answer: for a crystal structure the two are routinely different.
    """
    target = load_target(cif_with_unobs_category)
    findings = check_burial(target, [ResidueKey("A", 102)])
    codes = {f.code for f in findings}
    assert "NO_ASSEMBLY_DEFINED" in codes
    warn = next(f for f in findings if f.code == "NO_ASSEMBLY_DEFINED")
    assert warn.severity is Severity.WARN
    assert warn.key is None, "this is a site-level fact, not a per-residue one"
    assert "isolated chain" in warn.message


def test_unknown_chain_id_raises(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    with pytest.raises(ValueError, match="chain 'Z'"):
        check_burial(target, [ResidueKey("Z", 102)])


def test_unobserved_residue_warns_rather_than_kills(cif_with_unobs_category):
    """Author 104 is declared but unmodelled, so its SASA is undefined.

    WARN not KILL: the `resolved` check owns the verdict on missing atoms, and
    two checks must not both KILL for one underlying fact or the benchmark
    double-counts the reason.
    """
    target = load_target(cif_with_unobs_category)
    findings = check_burial(target, [ResidueKey("A", 104)])
    f = finding(findings, ResidueKey("A", 104), "RESIDUE_NOT_OBSERVED")
    assert f.severity is Severity.WARN
    assert "BURIED_IN_ASSEMBLY" not in codes_for(findings, ResidueKey("A", 104))


def test_empty_keys_raises(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    with pytest.raises(ValueError, match="no hotspot residues"):
        check_burial(target, [])


@pytest.mark.parametrize(
    "crop,match",
    [
        (("A", 103, 101), "runs backwards"),
        (("Z", 101, 103), "chain 'Z'"),
        (("A", 500, 600), "no observed residues"),
    ],
)
def test_crop_range_is_validated(cif_with_unobs_category, crop, match):
    target = load_target(cif_with_unobs_category)
    with pytest.raises(ValueError, match=match):
        check_burial(target, [ResidueKey("A", 102)], crop_range=crop)


def test_profile_records_every_pinned_parameter(cif_with_unobs_category):
    """A reader must be able to reproduce the number without reading the code."""
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    assert isinstance(profile, BurialProfile)
    assert profile.context == "chain"
    assert profile.n_chains == 1
    missing = REQUIRED_PARAMETER_KEYS - set(profile.parameters)
    assert not missing, f"unrecorded parameters: {sorted(missing)}"
    assert profile.parameters["probe_radius"] == SASA_PROBE_RADIUS
    assert profile.parameters["algorithm"] == "LeeRichards"
    assert profile.parameters["n_slices"] > 0
    assert profile.parameters["include_hydrogens"] is False
    assert profile.parameters["include_hetatm"] is False


def test_profile_keys_and_values_are_wellformed(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    assert set(profile.relative_sasa) == set(profile.absolute_sasa)
    assert ResidueKey("A", 101) in profile.relative_sasa
    assert ResidueKey("A", 104) not in profile.relative_sasa, "no atoms, no SASA"
    assert all(v >= 0.0 for v in profile.relative_sasa.values())
    assert all(v > 0.0 for v in profile.absolute_sasa.values())


def test_reference_falls_back_to_published_maxima_and_says_so(
    cif_with_unobs_category,
):
    """The fixture can only calibrate ALA; the rest must come from the table.

    ALA at author 102 is the one residue with both covalent neighbours present
    and contiguous, which is what the tripeptide reference requires.
    """
    target = load_target(cif_with_unobs_category)
    table, provenance = reference_max_sasa(target.st)
    assert provenance["ALA"] == "empirical"
    assert provenance["PHE"] == "published"
    assert table["PHE"] == PUBLISHED_MAX_SASA["PHE"]
    assert table["ALA"] > 0

    profile = compute_burial(target.st, context="chain", focus_chain="A")
    assert profile.parameters["n_reference_empirical"] >= 1
    assert profile.parameters["n_reference_published"] >= 1


def test_supplied_reference_is_used_rather_than_recomputed(cif_with_unobs_category):
    """The three contexts must share one denominator scale.

    If `compute_burial` quietly recomputed the reference from whatever it was
    handed, the crop -- a 20-residue fragment that can calibrate almost
    nothing -- would be scored against a different scale from the assembly,
    and the difference between the two ratios would stop meaning anything.
    Doubling the table must exactly halve the ratios; it only does if the
    supplied table is the one actually used.
    """
    target = load_target(cif_with_unobs_category)
    table, provenance = reference_max_sasa(target.st)

    baseline = compute_burial(
        target.st, context="chain", focus_chain="A", reference=(table, provenance)
    )
    doubled = compute_burial(
        target.st,
        context="chain",
        focus_chain="A",
        reference=({k: v * 2 for k, v in table.items()}, provenance),
    )
    assert set(baseline.relative_sasa) == set(doubled.relative_sasa)
    for key, value in baseline.relative_sasa.items():
        assert doubled.relative_sasa[key] == pytest.approx(value / 2)
    # Absolute areas are a property of the coordinates, not of the reference.
    assert doubled.absolute_sasa == baseline.absolute_sasa


def test_reference_digest_is_stable_across_processes(cif_with_unobs_category):
    """A stored reference_id must mean the same thing in a later run.

    Computed twice here, and deliberately not via `hash()`, which is salted
    per process: a digest that changed between runs would make every stored
    run record incomparable while looking perfectly well-formed.
    """
    target = load_target(cif_with_unobs_category)
    table, provenance = reference_max_sasa(target.st)
    assert reference_digest(table, provenance) == reference_digest(
        table, provenance
    )
    # Known-constant check: the digest must not depend on dict ordering.
    shuffled = dict(reversed(list(table.items())))
    assert reference_digest(shuffled, provenance) == reference_digest(
        table, provenance
    )
    # Provenance is part of the identity, not just the numbers.
    relabelled = {**provenance, "ALA": "published"}
    assert reference_digest(table, relabelled) != reference_digest(
        table, provenance
    )


REFERENCE_EVIDENCE_KEYS = (
    "reference_id",
    "n_reference_empirical",
    "n_reference_published",
    "n_reference_substituted",
    "n_fallback_radius_atoms",
    "focus_chain",
)


def test_every_residue_finding_carries_how_its_denominator_was_priced(
    cif_with_unobs_category,
):
    """A run record must state this without re-measuring to find it out.

    n_reference_published > 0 is the load-bearing one: it means some residue
    types could not be calibrated from this structure, so those relative
    values rest on the published fallback table. The synthetic fixture can
    only calibrate ALA, so it exercises exactly that case.
    """
    target = load_target(cif_with_unobs_category)
    findings = check_burial(target, [ResidueKey("A", 102), ResidueKey("A", 101)])
    residue_findings = [f for f in findings if f.key is not None]
    assert residue_findings

    for f in residue_findings:
        missing = [k for k in REFERENCE_EVIDENCE_KEYS if k not in f.evidence]
        assert not missing, f"{f.code} is missing {missing}"
        assert f.evidence["focus_chain"] == f.key.auth_asym_id
        assert f.evidence["n_reference_published"] > 0, "fixture calibrates only ALA"
        assert f.evidence["n_reference_empirical"] >= 1

    # The counters describe the scale, so they agree across every finding.
    assert len({f.evidence["reference_id"] for f in residue_findings}) == 1


@pytest.mark.network
def test_a_fully_calibrated_structure_reports_no_published_fallback(real_1tim: Path):
    """The counters have to be able to say 'all measured here', or they are noise."""
    target = load_target(real_1tim)
    findings = check_burial(target, [TIM_EXPOSED])
    ev = next(f.evidence for f in findings if f.key == TIM_EXPOSED)
    assert ev["n_reference_empirical"] == 20
    assert ev["n_reference_published"] == 0
    assert ev["n_reference_substituted"] == 0


def test_reference_id_is_recorded_on_the_profile(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    assert profile.reference_id
    assert profile.parameters["reference_id"] == profile.reference_id


def test_mismatched_reference_scales_refuse_to_compare(cif_with_unobs_category):
    """The guard that makes the shared-scale invariant structural.

    Two profiles of the same coordinates, measured against tables that differ
    by a constant factor, produce plausible in-range numbers whose deltas are
    nonsense. Comparing them must raise rather than return.
    """
    target = load_target(cif_with_unobs_category)
    table, provenance = reference_max_sasa(target.st)
    a = compute_burial(
        target.st, context="chain", focus_chain="A", reference=(table, provenance)
    )
    b = compute_burial(
        target.st,
        context="crop",
        focus_chain="A",
        reference=({k: v * 2 for k, v in table.items()}, provenance),
    )
    assert a.reference_id != b.reference_id

    with pytest.raises(ValueError, match="different reference scales"):
        compare_contexts(b, a)
    # The message must name both contexts so a reader can tell which drifted.
    with pytest.raises(ValueError, match="'crop'"):
        compare_contexts(b, a)


def test_matching_reference_scales_compare_cleanly(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    reference = reference_max_sasa(target.st)
    a = compute_burial(
        target.st, context="chain", focus_chain="A", reference=reference
    )
    b = compute_burial(
        target.st, context="assembly", focus_chain="A", reference=reference
    )
    deltas = compare_contexts(a, b)
    assert deltas, "the two profiles share residues"
    # Same coordinates, same scale, so every delta is exactly zero.
    assert all(abs(d) < 1e-12 for d in deltas.values())
    assert set(deltas) <= set(a.relative_sasa) & set(b.relative_sasa)


def _one_atom_chain(name: str, x: float) -> gemmi.Chain:
    chain = gemmi.Chain(name)
    res = gemmi.Residue()
    res.name = "ALA"
    res.seqid = gemmi.SeqId(1, " ")
    atom = gemmi.Atom()
    atom.name = "CA"
    atom.element = gemmi.Element("C")
    atom.pos = gemmi.Position(x, 0.0, 0.0)
    res.add_atom(atom)
    chain.add_residue(res)
    return chain


def _structure(*chains: gemmi.Chain) -> gemmi.Structure:
    st = gemmi.Structure()
    model = gemmi.Model("1")
    for chain in chains:
        model.add_chain(chain)
    st.add_model(model)
    return st


def test_identity_copy_is_found_by_coordinates_not_by_ordering():
    """gemmi happening to emit the identity copy first is not a contract.

    Both real fixtures have it first, so trusting the ordering passes on them
    and would mis-map every residue key the day gemmi changed. Here the
    identity copy is deliberately second.
    """
    original = _structure(_one_atom_chain("A", 0.0))
    expanded = _structure(
        _one_atom_chain("A2", 10.0),  # transformed copy, listed first
        _one_atom_chain("A1", 0.0),  # the identity copy
    )
    _restore_author_chain_names(original, expanded)

    renamed = {c.name: c[0][0].pos.x for c in expanded[0]}
    assert renamed["A"] == pytest.approx(0.0), "the untransformed copy must win"
    assert "A2" in renamed, "the transformed copy keeps its suffixed name"


def test_ambiguous_identity_copy_raises_rather_than_guessing():
    original = _structure(_one_atom_chain("A", 0.0))
    expanded = _structure(
        _one_atom_chain("A1", 0.0), _one_atom_chain("A2", 0.0)
    )
    with pytest.raises(ValueError, match="cannot identify the untransformed copy"):
        _restore_author_chain_names(original, expanded)


def test_expand_assembly_raises_when_none_is_declared(cif_with_unobs_category):
    """check_burial guards this path, so only a direct test covers the raise.

    Returning the asymmetric unit here instead would be the silent-wrong
    answer, and it would reach callers that do not do their own guarding.
    """
    target = load_target(cif_with_unobs_category)
    assert not target.st.assemblies
    with pytest.raises(ValueError, match="declares no biological assembly"):
        expand_assembly(target)


def test_expand_assembly_rejects_an_unknown_assembly_name(real_1tim: Path):
    target = load_target(real_1tim)
    with pytest.raises(ValueError, match="has no assembly 'nope'"):
        expand_assembly(target, "nope")


@pytest.mark.parametrize(
    "name,source",
    [
        ("BurialProfile", "sasa"),
        ("compute_burial", "sasa"),
        ("reference_max_sasa", "sasa"),
        ("reference_digest", "sasa"),
        ("trim_to_neighbourhood", "sasa"),
        ("PUBLISHED_MAX_SASA", "sasa"),
        ("REQUIRED_PARAMETER_KEYS", "sasa"),
        ("SASA_PROBE_RADIUS", "sasa"),
        ("NEIGHBOUR_CUTOFF_A", "sasa"),
        ("expand_assembly", "assembly"),
    ],
)
def test_api_is_reexported_not_reimplemented(name: str, source: str):
    """burial.py must stay a facade over sasa.py and assembly.py.

    Identity, not equality: if a split ever gets 'fixed' by pasting the moved
    code back into burial.py, there would be two copies of the pinned SASA
    parameters or of the chain-renaming rule, free to drift apart — and
    relative values measured through the two would stop being comparable.
    """
    from hotspot_preflight.checks import assembly as assembly_module
    from hotspot_preflight.checks import burial as burial_module

    origin = {"sasa": sasa_module, "assembly": assembly_module}[source]
    assert getattr(burial_module, name) is getattr(origin, name), name


def test_findings_survive_the_canonical_sort(cif_with_unobs_category):
    """Our findings must be orderable by the shared helper.

    This check is the one that emits a site-level finding
    (NO_ASSEMBLY_DEFINED, key is None) alongside per-residue ones, which is the
    case a naive `(key is None, key, ...)` sort key crashes on. `check_burial`
    itself returns caller order on purpose, so this pins compatibility rather
    than changing the contract.
    """
    target = load_target(cif_with_unobs_category)
    findings = check_burial(
        target, [ResidueKey("A", 103), ResidueKey("A", 101), ResidueKey("A", 104)]
    )
    assert any(f.key is None for f in findings), "fixture must hit the site-level path"

    ordered = sort_findings(findings)
    assert len(ordered) == len(findings)
    assert ordered[-1].code == "NO_ASSEMBLY_DEFINED", "site-level sorts last"
    assert sort_findings(ordered) == ordered, "sorting must be stable"
    # Caller order is preserved by check_burial itself, not by the sort.
    residue_order = [f.key for f in findings if f.key is not None]
    assert residue_order[0] == ResidueKey("A", 103)


# --------------------------------------------------------------------------
# 1TIM: the realistic multi-chain case
# --------------------------------------------------------------------------


@pytest.mark.network
def test_tim_assembly_is_the_dimer(real_1tim: Path):
    target = load_target(real_1tim)
    assert target.chain_ids == ["A", "B"]
    expanded = expand_assembly(target)
    names = [c.name for c in expanded[0]]
    # One generator, one operator: the deposited assembly is the dimer itself.
    assert names == ["A", "B"]


@pytest.mark.network
def test_expansion_preserves_the_identity_copy_coordinates(real_1tim: Path):
    """ResidueKeys from the asymmetric unit must index into the assembly.

    They only can if the copy we rename back to the author chain id is the
    untransformed one. Asserted rather than assumed.
    """
    target = load_target(real_1tim)
    expanded = expand_assembly(target)
    before = target.st[0]["A"][0][0].pos
    after = expanded[0]["A"][0][0].pos
    assert before.dist(after) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.network
def test_neighbour_search_ignores_crystal_symmetry(real_1tim: Path):
    """Lattice neighbours are not binding partners.

    1TIM is P 2 1 2 1 2 1 with a real cell, so gemmi's default NeighborSearch
    happily returns symmetry images -- which would make a crystal contact look
    like biological burial. The control half of this test proves the hazard is
    real rather than hypothetical.
    """
    target = load_target(real_1tim)
    model = target.st[0]

    control = gemmi.NeighborSearch(model, target.st.cell, 5.0).populate()
    ours = _neighbour_search(model, 5.0)  # the helper every caller here uses

    def images(search):
        found = set()
        for chain in model:
            for res in chain:
                for atom in res:
                    for mark in search.find_atoms(atom.pos, "\0", radius=5.0):
                        found.add(mark.image_idx)
        return found

    assert images(control) != {0}, "control: the real cell does return images"
    assert images(ours) == {0}, "ours must see the deposited copies only"


@pytest.mark.network
def test_trim_keeps_the_focus_chain_and_its_partners(real_1tim: Path):
    target = load_target(real_1tim)
    expanded = expand_assembly(target)
    trimmed = trim_to_neighbourhood(expanded, "A")
    names = {c.name for c in trimmed[0]}
    assert "A" in names
    assert "B" in names, "the partner is within the cutoff and must be kept"


@pytest.mark.network
def test_interface_residues_are_occluded_by_the_partner(tim_findings):
    """Loop 3 inserts into the partner subunit: the single-chain-vs-assembly case."""
    for key in (TIM_INTERFACE, TIM_INTERFACE_2):
        f = finding(tim_findings, key, "OCCLUDED_BY_PARTNER")
        assert f.severity is Severity.WARN
        ev = f.evidence
        assert ev["relative_sasa_chain"] > 0.8
        assert ev["relative_sasa_assembly"] < 0.01
        assert ev["relative_sasa_chain"] - ev["relative_sasa_assembly"] > (
            CROP_ARTIFACT_DELTA
        )


@pytest.mark.network
def test_exposed_residue_is_not_occluded(tim_findings):
    assert "OCCLUDED_BY_PARTNER" not in codes_for(tim_findings, TIM_EXPOSED)
    assert "BURIED_IN_ASSEMBLY" not in codes_for(tim_findings, TIM_EXPOSED)
    f = finding(tim_findings, TIM_EXPOSED, "EXPOSED")
    assert f.severity is Severity.PASS
    assert f.evidence["relative_sasa_assembly"] > 0.4


@pytest.mark.network
def test_interior_residue_is_killed(tim_findings):
    f = finding(tim_findings, TIM_INTERIOR, "BURIED_IN_ASSEMBLY")
    assert f.severity is Severity.KILL
    assert f.evidence["relative_sasa_assembly"] < BURIED_RELATIVE_SASA
    # The core is buried by its own chain, not by a partner.
    assert "OCCLUDED_BY_PARTNER" not in codes_for(tim_findings, TIM_INTERIOR)


@pytest.mark.network
def test_kill_message_names_what_buries_the_residue(tim_findings):
    """'Buried by chain B' is actionable; 'score 0.03' is not."""
    f = finding(tim_findings, TIM_INTERFACE, "BURIED_IN_ASSEMBLY")
    assert "B" in f.evidence["occluding_chains"]
    assert "chain B" in f.message


@pytest.mark.network
def test_crop_artifact_is_flagged_at_the_cut_faces(tim_findings):
    """The whole point: the crop face is exposed, the real surface is not."""
    f = finding(tim_findings, TIM_CUT_FACE, "CROP_ARTIFACT")
    assert f.severity is Severity.WARN
    assert f.evidence["relative_sasa_crop"] > 0.9
    assert f.evidence["relative_sasa_assembly"] < 0.2
    # Both numbers in the sentence, so the reader can disagree with us.
    assert "0.9" in f.message or "1.0" in f.message
    assert "crop" in f.message and "assembly" in f.message

    # The residue at the N-terminal cut is caught too.
    assert "CROP_ARTIFACT" in codes_for(tim_findings, ResidueKey("A", 70))


@pytest.mark.network
def test_crop_artifact_absent_when_no_crop_is_given(real_1tim: Path):
    target = load_target(real_1tim)
    findings = check_burial(target, [TIM_CUT_FACE])
    assert "CROP_ARTIFACT" not in {f.code for f in findings}


@pytest.mark.network
def test_empirical_reference_agrees_with_published_maxima(real_1tim: Path):
    """Cross-validate the two reference routes against each other.

    They are computed with different programs and different radii sets, so
    exact agreement is not expected -- but a large disagreement would mean the
    empirical route is measuring something other than maximal exposure.
    """
    target = load_target(real_1tim)
    table, provenance = reference_max_sasa(target.st)
    assert len(table) == 20, "1TIM contains every standard residue type"
    assert all(src == "empirical" for src in provenance.values())
    for name, empirical in table.items():
        ratio = empirical / PUBLISHED_MAX_SASA[name]
        assert 0.75 < ratio < 1.25, f"{name}: {empirical:.1f} vs published, {ratio=}"


# --------------------------------------------------------------------------
# 6F5J: the case the neighbourhood trim exists for
# --------------------------------------------------------------------------


@pytest.mark.network
def test_capsid_assembly_is_trimmed_before_sasa(real_6f5j: Path):
    """6F5J's one generator carries 60 operators: 3 chains become 180.

    Burial is local, so the trim is both correct and the only way this runs at
    capsid scale. NEIGHBOUR_CUTOFF_A is what bounds it.
    """
    target = load_target(real_6f5j)
    expanded = expand_assembly(target)
    assert len(expanded[0]) == 180

    trimmed = trim_to_neighbourhood(expanded, "A")
    assert 1 < len(trimmed[0]) < 40
    assert "A" in {c.name for c in trimmed[0]}

    profile = compute_burial(expanded, context="assembly", focus_chain="A")
    assert profile.context == "assembly"
    assert profile.n_chains == len(trimmed[0])
    assert profile.parameters["neighbour_cutoff_a"] == NEIGHBOUR_CUTOFF_A
    assert profile.relative_sasa, "the focus chain must still be profiled"
    assert all(k.auth_asym_id == "A" for k in profile.relative_sasa)


class TestTrimAcceptsSeveralFocusChains:
    """A multi-chain antigen must not lose a declared chain to the trim.

    The trim exists to stop an icosahedral capsid expanding to every copy, and
    its justification is that a chain beyond the cutoff cannot bury anything on
    the focus chain. That is true and it silently assumes one focus chain. On a
    two-chain antigen whose chains are far apart, trimming to the first drops the
    second — and with it every epitope residue on it, which the benchmark then
    scores as a false rejection by the filter rather than as a chain it threw
    away. Measured on 6hhd and 12ut before this was fixed.
    """

    def test_a_single_name_still_works(self, two_chain_structure):
        names = {c.name for c in trim_to_neighbourhood(two_chain_structure, "A")[0]}
        assert "A" in names

    def test_every_named_chain_is_kept_even_when_far_apart(
        self, two_chain_structure
    ):
        """The distant chain survives when it is named, and does not when it is
        not — so the test fails if the fixture's chains are accidentally close."""
        alone = {c.name for c in trim_to_neighbourhood(two_chain_structure, "A")[0]}
        assert "Z" not in alone, "fixture must place Z beyond the cutoff"

        both = {
            c.name for c in trim_to_neighbourhood(two_chain_structure, ["A", "Z"])[0]
        }
        assert {"A", "Z"} <= both

    def test_unknown_name_in_the_list_still_raises(self, two_chain_structure):
        """Silently ignoring a chain that is not there is how the original bug
        stayed invisible: the caller believes it protected a chain it did not."""
        with pytest.raises(ValueError, match="nope"):
            trim_to_neighbourhood(two_chain_structure, ["A", "nope"])

    def test_empty_list_is_rejected(self, two_chain_structure):
        with pytest.raises(ValueError):
            trim_to_neighbourhood(two_chain_structure, [])
