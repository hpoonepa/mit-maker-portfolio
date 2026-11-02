# SPDX-License-Identifier: MIT
"""Tests for the named weight profiles.

Mostly about honesty rather than arithmetic: the thing that can silently rot here
is not a score but a claim. ``n_outcomes_fitted`` must stay 0 for the profiles
nobody fitted, ``DEFAULT_WEIGHTS`` must stay the *same object* as
:data:`DESIGNABILITY`'s weights rather than drift into a stale copy, and a
profile must not be able to exist without a written account of where it came
from.
"""

from __future__ import annotations

import pytest

from hotspot_preflight.checks.burial import compute_burial
from hotspot_preflight.predict.geometric import (
    DEFAULT_WEIGHTS,
    FEATURE_NAMES,
    GeometricPredictor,
    exposure_feature,
)
from hotspot_preflight.predict.profiles import (
    ANTIBODY_EPITOPE,
    DESIGNABILITY,
    EXPOSURE_ONLY,
    PROFILES,
    WeightProfile,
    get_profile,
)
from hotspot_preflight.structure import load_target

UNFITTED = (DESIGNABILITY, EXPOSURE_ONLY)


# ---------------------------------------------------------------------------
# Shape: what every profile has to satisfy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda p: p.name)
def test_every_profile_weights_only_known_features(profile):
    """A weight on a feature that does not exist is a weight that does nothing."""
    assert set(profile.weights) <= set(FEATURE_NAMES)
    assert profile.weights, "a profile with no weights ranks nothing"


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda p: p.name)
def test_every_profile_is_keyed_by_its_own_name(profile):
    assert PROFILES[profile.name] is profile


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda p: p.name)
def test_every_profile_carries_provenance(profile):
    """The whole point of the class. Weights without this are a bare number."""
    assert len(profile.provenance.strip()) > 100


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda p: p.name)
def test_profile_weights_are_frozen(profile):
    """A shared module-level profile must not be mutable by one caller."""
    with pytest.raises(TypeError):
        profile.weights["exposure"] = 99.0  # type: ignore[index]


def test_the_convex_profiles_sum_to_one_and_the_fitted_one_does_not():
    """Documented per profile, and the distinction is load-bearing.

    The two hand-set profiles are convex combinations, so a residue score is
    bounded in [0, 1] and readable as a fraction. ``ANTIBODY_EPITOPE`` holds
    log-odds coefficients, where only the ranking means anything — asserting a
    sum of 1.0 for all three would be asserting a property the fit does not and
    should not have.
    """
    assert sum(DESIGNABILITY.weights.values()) == pytest.approx(1.0)
    assert sum(EXPOSURE_ONLY.weights.values()) == pytest.approx(1.0)
    assert sum(ANTIBODY_EPITOPE.weights.values()) != pytest.approx(1.0)


# ---------------------------------------------------------------------------
# n_outcomes_fitted: the number that must not be flattering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", UNFITTED, ids=lambda p: p.name)
def test_the_unfitted_profiles_report_zero_outcomes(profile):
    """Hand-set weights were fitted to nothing, however well reasoned."""
    assert profile.n_outcomes_fitted == 0




def test_a_profile_cannot_claim_a_negative_or_missing_provenance():
    with pytest.raises(ValueError, match="n_outcomes_fitted"):
        WeightProfile(
            name="bad", weights={"exposure": 1.0}, provenance="x", n_outcomes_fitted=-1
        )
    with pytest.raises(ValueError, match="empty provenance"):
        WeightProfile(name="bad", weights={"exposure": 1.0}, provenance="   ")


def test_a_profile_rejects_an_unknown_feature_name():
    with pytest.raises(ValueError, match="unknown feature"):
        WeightProfile(
            name="bad", weights={"exposre": 1.0}, provenance="a typo, caught"
        )




# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_get_profile_returns_the_profile_by_name(name):
    assert get_profile(name) is PROFILES[name]


def test_get_profile_names_the_available_profiles_on_an_unknown_name():
    """The caller is usually a CLI user or a config file; a typo deserves a list."""
    with pytest.raises(ValueError) as excinfo:
        get_profile("antibody")
    message = str(excinfo.value)
    assert "antibody" in message
    for name in PROFILES:
        assert name in message


# ---------------------------------------------------------------------------
# DEFAULT_WEIGHTS is an alias, not a copy
# ---------------------------------------------------------------------------


def test_default_weights_is_the_same_object_as_the_designability_weights():
    """Identity, not equality.

    Equality would pass against a duplicated literal, and a duplicated literal
    is how the two drift apart — with the copy nobody reads being the one still
    in use.
    """
    assert DEFAULT_WEIGHTS is DESIGNABILITY.weights


def test_the_default_predictor_uses_the_designability_profile_unchanged():
    """Which profile is the default is a claim about the tool, so it is pinned.

    Changing it is a deliberate decision, not a refactor, and this test is where
    that decision has to be made explicitly.
    """
    predictor = GeometricPredictor()
    assert predictor.profile is DESIGNABILITY
    assert predictor.weights is DESIGNABILITY.weights
    assert predictor.n_outcomes_fitted == 0


# ---------------------------------------------------------------------------
# A profile actually changes the ranking
# ---------------------------------------------------------------------------


@pytest.fixture
def hand_built(cif_with_unobs_category):
    """The shared synthetic chain: GLY, ALA, VAL, PHE on a line.

    Hand-built rather than a real protein, so an expected score follows from the
    geometry. It also happens to be the case that separates these profiles: GLY
    scores 0 on hydrophobicity and PHE scores 1, and the two end residues are the
    most exposed, so a predictor ranking purely by exposure and one weighting
    hydrophobicity cannot agree by accident.
    """
    target = load_target(cif_with_unobs_category)
    burial = compute_burial(target.st, context="chain", focus_chain="A")
    return target, burial


def test_exposure_only_ranks_purely_by_exposure(hand_built):
    """Every score equals that residue's exposure feature exactly.

    Equal, not merely correlated: a stray hydrophobicity or concavity term could
    otherwise hide inside a ranking that happened to come out in the right order.
    """
    target, burial = hand_built
    predictor = GeometricPredictor(profile=EXPOSURE_ONLY)

    scores = predictor.score_residues(target, burial)
    assert scores, "nothing was scored, so nothing was asserted"
    for key, score in scores.items():
        assert score == pytest.approx(exposure_feature(key, burial))

    for breakdown in predictor.score_components(target, burial).values():
        assert breakdown["concavity"] == 0.0
        assert breakdown["hydrophobicity"] == 0.0
        assert breakdown["connectivity"] == 0.0


def test_the_profiles_disagree_on_the_hand_built_case(hand_built):
    """The mechanism has to be able to change an answer.

    A mechanism that threads a profile through but always produces the same
    ranking would pass every other test in this file.
    """
    target, burial = hand_built
    by_exposure = GeometricPredictor(profile=EXPOSURE_ONLY).score_residues(
        target, burial
    )
    by_designability = GeometricPredictor().score_residues(target, burial)
    by_fit = GeometricPredictor(profile=ANTIBODY_EPITOPE).score_residues(
        target, burial
    )
    assert by_exposure != by_designability
    assert by_exposure != by_fit
    assert by_designability != by_fit


def test_explicit_weights_override_the_profile_and_forfeit_its_evidence():
    """Hand-supplied weights inherit none of a fitted profile's provenance."""
    swept = GeometricPredictor(
        profile=ANTIBODY_EPITOPE, weights={"exposure": 1.0, "concavity": -1.0}
    )
    assert swept.weights["concavity"] == -1.0
    assert swept.n_outcomes_fitted == 0, (
        "hand-supplied weights do not inherit fitted outcome evidence"
    )
    assert GeometricPredictor(profile=ANTIBODY_EPITOPE).n_outcomes_fitted == ANTIBODY_EPITOPE.n_outcomes_fitted


def test_an_empty_weight_mapping_is_not_mistaken_for_the_profile_default():
    """The 'take it from the profile' sentinel is identity-checked, not truthiness.

    Passing ``{}`` is a legitimate if useless request for an all-zero ranking,
    and must not silently become the profile's weights.
    """
    predictor = GeometricPredictor(profile=ANTIBODY_EPITOPE, weights={})
    assert dict(predictor.weights) == {}
    assert predictor.n_outcomes_fitted == 0


class TestWeightProfileName:
    """``weight_profile_name`` is what a run record should report.

    It exists alongside ``profile`` because ``profile`` is the *requested*
    profile and stays set when ``weights`` overrides it — reporting that name
    would attribute a ranking to weights that did not produce it.
    """

    def test_reports_the_profile_when_weights_came_from_it(self) -> None:
        from hotspot_preflight.predict.geometric import GeometricPredictor

        assert (
            GeometricPredictor(profile=ANTIBODY_EPITOPE).weight_profile_name
            == "antibody_epitope"
        )

    def test_defaults_to_designability(self) -> None:
        from hotspot_preflight.predict.geometric import GeometricPredictor

        assert GeometricPredictor().weight_profile_name == "designability"

    def test_is_none_when_weights_were_overridden(self) -> None:
        """The case that makes this a separate property: hand-typed weights are
        not a named profile, and a record saying 'designability' here would be
        false."""
        from hotspot_preflight.predict.geometric import GeometricPredictor

        pred = GeometricPredictor(weights={"exposure": 1.0})
        assert pred.profile.name == "designability"
        assert pred.weight_profile_name is None

    def test_agrees_with_n_outcomes_fitted_about_overrides(self) -> None:
        """Both answer 'are these the profile's weights'. They must not be able
        to disagree, so they are pinned to each other here."""
        from hotspot_preflight.predict.geometric import GeometricPredictor

        for pred in (
            GeometricPredictor(),
            GeometricPredictor(profile=ANTIBODY_EPITOPE),
            GeometricPredictor(profile=ANTIBODY_EPITOPE, weights={"exposure": 1.0}),
            GeometricPredictor(weights={}),
        ):
            if pred.weight_profile_name is None:
                assert pred.n_outcomes_fitted == 0
            else:
                assert pred.weight_profile_name == pred.profile.name
                assert pred.n_outcomes_fitted == pred.profile.n_outcomes_fitted

        # The override case has to be exercised by at least one of the above,
        # or this test would pass on a property that always returned a name.
        assert (
            GeometricPredictor(
                profile=ANTIBODY_EPITOPE, weights={"exposure": 1.0}
            ).weight_profile_name
            is None
        )
