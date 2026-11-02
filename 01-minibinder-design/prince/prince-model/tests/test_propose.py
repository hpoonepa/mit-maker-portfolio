"""Proposing sites, tested as library code and then through the CLI.

Three properties here are worth more than the rest, because each one fails
*silently* if it regresses — the output stays plausible and nothing raises:

* **One reference table.** Relative SASA is an area over a per-residue-type
  maximum, so a per-context recompute rescales every denominator while keeping
  values in range and in order. ``reference_id`` is the only visible evidence.
* **Suppression before the window.** ``enumerate_patches`` grows one patch per
  seed, so a top-k taken before near-duplicates are collapsed is partly a
  statement about enumeration density rather than about the sites.
* **``anchor_max`` is never thresholded.** On a maximum, one occluded rim residue
  speaks for a whole patch, which mass-kills surface near any oligomer contact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hotspot_preflight.cli import app
from hotspot_preflight.predict import get
from hotspot_preflight.propose import (
    ProposedSites,
    propose_sites,
    rank_candidates,
    render_propose_text,
    to_propose_record,
)
from hotspot_preflight.structure import load_target

# Imported rather than duplicated: conftest.py belongs to another agent, so the
# shared literal lives in the test module that first needed it.
from test_cli import _ASSEMBLY_CATEGORIES

runner = CliRunner()


@pytest.fixture
def cif_with_assembly(cif_with_unobs_category: Path, tmp_path: Path) -> Path:
    out = tmp_path / "with_assembly.cif"
    out.write_text(cif_with_unobs_category.read_text() + _ASSEMBLY_CATEGORIES)
    return out


@pytest.fixture
def sites(cif_with_assembly: Path) -> ProposedSites:
    return propose_sites(load_target(cif_with_assembly), get("geometric"))


# --- The pipeline ---------------------------------------------------------


def test_propose_sites_measures_on_the_declared_assembly(
    sites: ProposedSites,
) -> None:
    assert sites.chain == "A"
    assert sites.assembly_id == "1"
    assert sites.context == "assembly"
    assert sites.predictor == "geometric"


def test_propose_sites_falls_back_to_the_chain_without_an_assembly(
    cif_with_unobs_category: Path,
) -> None:
    """Reported as context "chain" rather than claimed as the biological form."""
    out = propose_sites(load_target(cif_with_unobs_category), get("geometric"))
    assert out.assembly_id is None
    assert out.context == "chain"


def test_every_measurement_shares_one_reference_scale(
    sites: ProposedSites, cif_with_assembly: Path
) -> None:
    """The reference_id the proposal reports is the one burial would produce.

    A per-context recompute would change this digest while leaving every score
    looking reasonable, so the digest is the only thing that can catch it.
    """
    from hotspot_preflight.checks.burial import compute_burial, reference_max_sasa

    target = load_target(cif_with_assembly)
    expected = compute_burial(
        target.st,
        context="chain",
        focus_chain="A",
        reference=reference_max_sasa(target.st),
    )
    assert sites.reference_id == expected.reference_id


def test_suppression_runs_before_any_window(sites: ProposedSites) -> None:
    """A rank is only meaningful against the suppressed count."""
    assert sites.n_after_suppression <= sites.n_enumerated
    assert sites.n_after_suppression == len(sites.ranked)


def test_ranking_is_descending_by_score(sites: ProposedSites) -> None:
    scores = [s.score for s in sites.ranked]
    assert scores == sorted(scores, reverse=True)


def test_top_is_a_prefix_of_the_ranking(sites: ProposedSites) -> None:
    assert sites.top(2) == sites.ranked[:2]


def test_top_rejects_a_nonpositive_count(sites: ProposedSites) -> None:
    """Zero would return nothing, which reads as "no sites found"."""
    with pytest.raises(ValueError, match="at least 1"):
        sites.top(0)


def test_unknown_chain_is_refused_rather_than_substituted(
    cif_with_assembly: Path,
) -> None:
    with pytest.raises(ValueError, match="not in"):
        propose_sites(load_target(cif_with_assembly), get("geometric"), chain="Z")


def test_rank_candidates_suppresses_for_a_predictor_without_rank(
    cif_with_assembly: Path, sites: ProposedSites
) -> None:
    """A backend that only implements score_residues still gets suppression.

    SitePredictor requires only score_residues, so the fallback path is what an
    external score file takes. Without it, that backend would silently return an
    unsuppressed ranking and its top-k would mean something different from the
    geometric backend's.
    """
    from hotspot_preflight.checks.burial import compute_burial, reference_max_sasa
    from hotspot_preflight.surface import enumerate_patches

    target = load_target(cif_with_assembly)
    reference = reference_max_sasa(target.st)
    profile = compute_burial(
        target.st, context="chain", focus_chain="A", reference=reference
    )
    patches = enumerate_patches(target.st, profile, chain="A")

    inner = get("geometric")

    class ScoreOnly:
        """Deliberately exposes no ``rank``, exercising the fallback."""

        name = "score-only"

        def score_residues(self, t, p):
            return inner.score_residues(t, p)

    ranked = rank_candidates(ScoreOnly(), target, profile, patches)
    assert ranked
    assert all(s.predictor == "score-only" for s in ranked)
    assert len(ranked) <= len(patches)


# --- The artifacts --------------------------------------------------------


def test_record_round_trips_and_names_its_reference_scale(
    sites: ProposedSites,
) -> None:
    record = to_propose_record(sites, 2)
    assert json.loads(json.dumps(record, sort_keys=True)) == record
    assert record["reference_id"] == sites.reference_id
    assert record["n_shown"] == len(record["patches"]) <= 2
    assert record["n_patches_enumerated"] == sites.n_enumerated


def test_record_carries_no_path_beyond_the_filename(
    sites: ProposedSites, cif_with_assembly: Path
) -> None:
    record = to_propose_record(sites, 1)
    assert record["input_filename"] == "with_assembly.cif"
    assert str(cif_with_assembly.parent) not in json.dumps(record)


def test_record_emits_anchor_max_only_under_its_warning_name(
    sites: ProposedSites,
) -> None:
    for patch in to_propose_record(sites, 5)["patches"]:
        assert "anchor_max_do_not_threshold" in patch
        assert "anchor_max" not in patch


def test_render_returns_a_table_and_does_not_print(
    sites: ProposedSites, capsys: pytest.CaptureFixture[str]
) -> None:
    text = render_propose_text(sites, 3)
    assert "candidate patches" in text
    assert "after overlap suppression" in text
    assert "rank" in text and "residues" in text
    assert "\x1b[" not in text
    assert capsys.readouterr() == ("", "")


def test_render_states_both_counts_so_a_rank_has_a_denominator(
    sites: ProposedSites,
) -> None:
    text = render_propose_text(sites, 1)
    assert str(sites.n_enumerated) in text
    assert str(sites.n_after_suppression) in text


def test_render_shows_anchor_mean_and_not_anchor_max(sites: ProposedSites) -> None:
    text = render_propose_text(sites, 5)
    assert "anchor" in text
    maxima = {
        f"{s.anchor_max:.3f}"
        for s in sites.top(5)
        if s.anchor_max is not None and s.anchor_max == s.anchor_max
    }
    means = {
        f"{s.anchor_mean:.3f}"
        for s in sites.top(5)
        if s.anchor_mean is not None and s.anchor_mean == s.anchor_mean
    }
    # Only meaningful where the two differ; on this fixture they do.
    for value in maxima - means:
        assert value not in text


# --- Through the CLI ------------------------------------------------------


def test_cli_propose_exits_0_and_emits_the_requested_count(
    cif_with_assembly: Path,
) -> None:
    result = runner.invoke(
        app, ["propose", str(cif_with_assembly), "--chain", "A", "--top", "2"]
    )
    assert result.exit_code == 0, result.output
    assert "candidate patches" in result.output
    rows = [line for line in result.output.splitlines() if line.strip()[:1].isdigit()]
    assert len(rows) == 2


def test_cli_propose_writes_json(cif_with_assembly: Path, tmp_path: Path) -> None:
    out = tmp_path / "sites.json"
    result = runner.invoke(
        app,
        ["propose", str(cif_with_assembly), "--top", "3", "--json", str(out),
         "--quiet"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""
    record = json.loads(out.read_text())
    assert record["chain"] == "A" and record["predictor"] == "geometric"
    assert record["n_shown"] == len(record["patches"]) <= 3


def test_cli_propose_exit_3_on_an_unknown_predictor(
    cif_with_assembly: Path,
) -> None:
    result = runner.invoke(
        app, ["propose", str(cif_with_assembly), "--predictor", "nope"]
    )
    assert result.exit_code == 3, result.output
    assert "geometric" in result.output
    assert "Traceback" not in result.output


def test_cli_propose_exit_3_on_an_unknown_chain(cif_with_assembly: Path) -> None:
    result = runner.invoke(app, ["propose", str(cif_with_assembly), "--chain", "Z"])
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_cli_propose_exit_3_on_a_nonpositive_top(
    cif_with_assembly: Path, bad: str
) -> None:
    result = runner.invoke(app, ["propose", str(cif_with_assembly), "--top", bad])
    assert result.exit_code == 3, result.output


def test_cli_propose_exit_3_on_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["propose", str(tmp_path / "nope.cif")])
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


def test_cli_propose_never_returns_a_verdict_exit_code(
    cif_with_assembly: Path,
) -> None:
    """0 or 3 only. It reports candidates and passes no verdict, so a pipeline
    must not be able to gate on it as though it had."""
    for args in (
        [str(cif_with_assembly)],
        [str(cif_with_assembly), "--chain", "A"],
        [str(cif_with_assembly), "--top", "1"],
    ):
        result = runner.invoke(app, ["propose", *args])
        assert result.exit_code in (0, 3), result.output


def test_cli_propose_help_documents_its_two_exit_codes() -> None:
    result = runner.invoke(app, ["propose", "--help"])
    assert result.exit_code == 0
    assert "0" in result.output and "3" in result.output


def test_render_names_the_weight_profile(sites: ProposedSites) -> None:
    """The header must attribute the ranking to its weight profile.

    Two profiles rank the same chain differently and one of them is below chance
    on antibody epitopes, so a pasted table that names only the predictor cannot
    be attributed. The suppression count is itself profile-dependent — NMS
    removes patches in score order — so even the denominators printed beside it
    depend on this parameter.
    """
    text = render_propose_text(sites, 3)
    assert sites.weight_profile is not None, "fixture must exercise the named case"
    assert sites.weight_profile in text.splitlines()[0]


def test_render_marks_hand_set_weights_rather_than_naming_a_profile(
    sites: ProposedSites,
) -> None:
    """Hand-typed weights are reported as such, not left to read as the default
    profile and not attributed to one."""
    from dataclasses import replace

    from hotspot_preflight.propose import CUSTOM_WEIGHTS

    text = render_propose_text(replace(sites, weight_profile=CUSTOM_WEIGHTS), 3)
    first = text.splitlines()[0]
    assert "custom weights" in first
    for name in ("designability", "antibody_epitope", "exposure_only"):
        assert name not in first


def test_render_omits_the_clause_for_a_backend_with_no_weights(
    sites: ProposedSites,
) -> None:
    """``None`` means the backend has no weights to name — an external score file
    is read, not reweighted — so the header must not claim any weighting."""
    from dataclasses import replace

    first = render_propose_text(
        replace(sites, weight_profile=None), 3
    ).splitlines()[0]
    assert "weights" not in first


def test_custom_weights_is_distinguishable_from_no_weights_in_the_record() -> None:
    """The distinction this field exists to make. A hand-tuned geometric run and
    a predictor that never had weights must not look the same in the JSON."""
    from hotspot_preflight.predict.geometric import GeometricPredictor
    from hotspot_preflight.propose import CUSTOM_WEIGHTS, _weight_profile_of

    class NoWeights:
        name = "external"

    assert _weight_profile_of(GeometricPredictor()) == "designability"
    assert (
        _weight_profile_of(GeometricPredictor(weights={"exposure": 1.0}))
        == CUSTOM_WEIGHTS
    )
    assert _weight_profile_of(NoWeights()) is None
