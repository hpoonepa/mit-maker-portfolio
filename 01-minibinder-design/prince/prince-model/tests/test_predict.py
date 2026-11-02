# SPDX-License-Identifier: MIT
"""Tests for the site-proposal stage.

Each geometric feature is asserted on a hand-written geometry with an exact
expected value, rather than on a real structure, so a test failure points at the
definition rather than at the protein. The one real-structure test is marked
``network`` and deliberately asserts a weak claim; see its docstring.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import gemmi
import pytest

from hotspot_preflight.checks.burial import (
    compute_burial,
    expand_assembly,
    reference_max_sasa,
    trim_to_neighbourhood,
)
from hotspot_preflight.checks.sasa import BurialProfile
from hotspot_preflight.predict import registry
from hotspot_preflight.predict.base import ScoredPatch, rank_patches
from hotspot_preflight.predict.base import (
    NMS_JACCARD_THRESHOLD,
    EXTERNAL_PRIOR_DEFAULT_WEIGHT,
    N_OUTCOMES_FITTED,
    jaccard,
    provenance,
    suppress_overlapping,
)
from hotspot_preflight.predict.external import (
    MIN_MATCH_FRACTION,
    UNSCORED,
    ExternalPredictor,
    ExternalScoreError,
    LowResidueMatchWarning,
    load_external_score_file,
    load_external_scores,
    midrank_percentiles,
)
from hotspot_preflight.predict.geometric import (
    CONNECTIVITY_REFERENCE,
    DEFAULT_WEIGHTS,
    FEATURE_NAMES,
    GeometricPredictor,
    concavity_feature,
    connectivity_feature,
    anchor_residues,
    exposure_feature,
    hydrophobicity_feature,
    residue_names,
    residue_points,
)
from hotspot_preflight.predict.registry import (
    PredictorPluginWarning,
    PredictorRegistry,
    UnknownPredictorError,
)
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import load_target
from hotspot_preflight.surface import Patch, enumerate_patches

K = ResidueKey


# ---------------------------------------------------------------------------
# Hand-built helpers
# ---------------------------------------------------------------------------


def make_patch(
    residues: tuple[ResidueKey, ...],
    area: float = 100.0,
    mean_relative_sasa: float = 0.5,
    centroid: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Patch:
    return Patch(
        residues=residues,
        centroid=centroid,
        area=area,
        mean_relative_sasa=mean_relative_sasa,
    )


def make_profile(
    relative: dict[ResidueKey, float], focus_chain: str | None = "A"
) -> BurialProfile:
    """A profile carrying only what the predictor reads from one."""
    return BurialProfile(
        relative_sasa=dict(relative),
        absolute_sasa={k: v * 200.0 for k, v in relative.items()},
        context="assembly",
        n_chains=1,
        parameters={"focus_chain": focus_chain},
    )


def cross(radius: float, z: float) -> list[tuple[float, float, float]]:
    """Four points on the axes at ``radius``, at height ``z``.

    Axis-aligned and in signed pairs so the centroid's x and y are *exactly*
    zero in floating point, which makes the local normal exactly (0, 0, +-1) and
    the expected concavity exact rather than within a tolerance. A trigonometric
    ring leaves x and y at ~1e-17, which can tip a dot product that should be
    exactly 0 to the positive side and make the assertion flaky.
    """
    return [
        (radius, 0.0, z),
        (-radius, 0.0, z),
        (0.0, radius, z),
        (0.0, -radius, z),
    ]


def points_from(
    centre: tuple[float, float, float], others: list[tuple[float, float, float]]
) -> dict[ResidueKey, tuple[float, float, float]]:
    out = {K("A", 1): centre}
    for i, p in enumerate(others, start=2):
        out[K("A", i)] = p
    return out


# ---------------------------------------------------------------------------
# exposure_feature
# ---------------------------------------------------------------------------


def test_exposure_feature_is_the_profiles_relative_sasa():
    profile = make_profile({K("A", 10): 0.42})
    assert exposure_feature(K("A", 10), profile) == pytest.approx(0.42)


def test_exposure_feature_clamps_above_one():
    """Relative SASA over 1.0 is real on a cut crop face and must not win.

    reference_max_sasa's denominator is the most exposed instance in the
    structure, so a freshly exposed crop face can beat it. Unclamped, the
    artifact would outrank every genuine site.
    """
    profile = make_profile({K("A", 10): 1.8})
    assert exposure_feature(K("A", 10), profile) == pytest.approx(1.0)


def test_the_exposure_clamp_stops_a_crop_artifact_outranking_a_real_site():
    """PIN. Deleting the ``min()`` in exposure_feature inverts this ranking.

    This is the consequence test, not the unit test above. A freshly cut crop
    face has relative SASA above 1.0 because the denominator is the most
    exposed instance of that residue type in the intact structure, which a cut
    face can beat. Unclamped, exposure alone makes the artifact outscore a
    *fully* exposed genuine site - so the proposal stage would systematically
    prefer the exact pathology the burial check exists to kill, and the two
    halves of the tool would be working against each other.

    The symptom would be top-ranked patches clustering on crop boundaries,
    which reads as a conceptual failure of the whole approach rather than as
    one missing call, so it is pinned here rather than only documented.
    """
    weight = DEFAULT_WEIGHTS["exposure"]
    artifact = K("A", 1)  # on a cut crop face: relative SASA 1.8
    genuine = K("A", 2)  # real surface, as exposed as a residue ever gets: 1.0
    profile = make_profile({artifact: 1.8, genuine: 1.0})

    clamped = {k: weight * exposure_feature(k, profile) for k in (artifact, genuine)}
    unclamped = {k: weight * profile.relative_sasa[k] for k in (artifact, genuine)}

    # The advantage the clamp removes is real, and is what this test guards.
    assert unclamped[artifact] > unclamped[genuine]
    assert clamped[artifact] == pytest.approx(clamped[genuine])

    # So the genuine patch wins on the next tie-break (area) instead of losing
    # outright. Without the clamp the artifact takes rank 1 and this fails.
    ranked = rank_patches(
        [make_patch((artifact,), area=10.0), make_patch((genuine,), area=99.0)],
        clamped,
        predictor_name="geometric",
    )
    assert ranked[0].patch.residues == (genuine,)


def test_exposure_feature_of_unprofiled_residue_is_zero():
    assert exposure_feature(K("A", 99), make_profile({K("A", 10): 0.5})) == 0.0


# ---------------------------------------------------------------------------
# concavity_feature
# ---------------------------------------------------------------------------


def test_concavity_of_a_protruding_residue_is_zero():
    """A knob at z=6 over a flat bed: every neighbour lies behind the plane."""
    points = points_from((0.0, 0.0, 6.0), cross(3.0, 0.0) + cross(5.0, 0.0))
    assert concavity_feature(K("A", 1), points) == 0.0


def test_concavity_of_a_flat_face_is_zero():
    """In-plane neighbours give dot == 0, which is not > 0.

    Flat and protruding both score 0 by construction; the feature's docstring
    says so, and exposure_feature is what separates them.
    """
    points = points_from((0.0, 0.0, 0.0), cross(6.0, 0.0) + cross(2.0, -5.0))
    assert concavity_feature(K("A", 1), points) == 0.0


def test_concavity_of_a_groove_floor_counts_the_walls():
    """8 residues of bulk beneath, 4 rim residues above: exactly 4/12.

    The bulk outnumbers the rim, so the local normal points up out of the
    groove; the rim then sits on the solvent side of the tangent plane through
    the floor residue and is counted.
    """
    points = points_from(
        (0.0, 0.0, 0.0), cross(3.0, -4.0) + cross(5.0, -4.0) + cross(6.0, 4.0)
    )
    assert concavity_feature(K("A", 1), points) == pytest.approx(4.0 / 12.0)


def test_concavity_respects_the_radius_cutoff():
    """The same groove with its rim moved out of range scores 0 instead."""
    points = points_from(
        (0.0, 0.0, 0.0), cross(3.0, -4.0) + cross(5.0, -4.0) + cross(20.0, 4.0)
    )
    assert concavity_feature(K("A", 1), points) == 0.0


def test_concavity_with_no_neighbours_is_zero():
    assert concavity_feature(K("A", 1), {K("A", 1): (0.0, 0.0, 0.0)}) == 0.0


def test_concavity_with_a_degenerate_normal_is_zero():
    """A residue exactly at its neighbourhood centroid has no normal direction.

    Returning 0.0 rather than dividing by a near-zero length, which would make
    the direction - and therefore the feature - numerical noise.
    """
    points = points_from(
        (0.0, 0.0, 0.0), cross(5.0, 0.0) + [(0.0, 0.0, 5.0), (0.0, 0.0, -5.0)]
    )
    assert concavity_feature(K("A", 1), points) == 0.0


def test_concavity_of_an_absent_residue_is_zero():
    assert concavity_feature(K("A", 77), points_from((0.0, 0.0, 0.0), [])) == 0.0


# ---------------------------------------------------------------------------
# hydrophobicity_feature
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["LEU", "ILE", "PHE", "TRP", "CYS", "TYR", "leu"])
def test_hydrophobicity_of_nonpolar_types_is_one(name):
    assert hydrophobicity_feature(name) == 1.0


@pytest.mark.parametrize("name", ["ASP", "GLU", "LYS", "ARG", "SER", "GLY", "HIS"])
def test_hydrophobicity_of_polar_types_is_zero(name):
    assert hydrophobicity_feature(name) == 0.0


def test_hydrophobicity_of_selenomethionine_is_zero():
    """MSE is a phasing trick, not biology; a site must not score on it."""
    assert hydrophobicity_feature("MSE") == 0.0


def test_hydrophobicity_of_an_unknown_type_is_zero():
    assert hydrophobicity_feature("XYZ") == 0.0


def test_patch_mean_of_hydrophobicity_is_the_hydrophobic_fraction():
    """The reason the feature is binary: the patch mean is countable by hand."""
    names = ["LEU", "PHE", "ASP", "LYS"]
    values = [hydrophobicity_feature(n) for n in names]
    assert sum(values) / len(values) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# connectivity_feature
# ---------------------------------------------------------------------------


def test_connectivity_counts_only_surface_neighbours_within_the_radius():
    """4 surface neighbours in range out of a reference of 8 gives exactly 0.5."""
    points = {
        K("A", 1): (0.0, 0.0, 0.0),
        K("A", 2): (4.0, 0.0, 0.0),
        K("A", 3): (0.0, 4.0, 0.0),
        K("A", 4): (0.0, 0.0, 4.0),
        K("A", 5): (-4.0, 0.0, 0.0),
        K("A", 6): (40.0, 0.0, 0.0),  # in the surface set but out of range
        K("A", 7): (0.0, 0.0, -4.0),  # in range but not in the surface set
    }
    surface = [K("A", i) for i in (1, 2, 3, 4, 5, 6)]
    assert connectivity_feature(K("A", 1), points, surface) == pytest.approx(
        4.0 / CONNECTIVITY_REFERENCE
    )


def test_connectivity_saturates_at_one():
    points = {K("A", 1): (0.0, 0.0, 0.0)}
    for i in range(2, 22):
        points[K("A", i)] = (float(i % 3), float(i % 5), 1.0)
    assert connectivity_feature(
        K("A", 1), points, list(points)
    ) == pytest.approx(1.0)


def test_connectivity_of_an_isolated_residue_is_zero():
    points = {K("A", 1): (0.0, 0.0, 0.0), K("A", 2): (50.0, 0.0, 0.0)}
    assert connectivity_feature(K("A", 1), points, list(points)) == 0.0


def test_connectivity_of_an_absent_residue_is_zero():
    assert connectivity_feature(K("A", 9), {K("A", 1): (0.0, 0.0, 0.0)}, []) == 0.0


# ---------------------------------------------------------------------------
# residue_points / residue_names
# ---------------------------------------------------------------------------


def _one_residue_structure() -> gemmi.Structure:
    st = gemmi.Structure()
    st.name = "HAND"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    res = gemmi.Residue()
    res.name = "LEU"
    res.seqid = gemmi.SeqId(201, " ")
    for name, element, pos in (
        ("N", "N", (0.0, 0.0, 0.0)),
        ("CA", "C", (3.0, 0.0, 0.0)),
        ("CB", "C", (0.0, 6.0, 0.0)),
        ("H", "H", (100.0, 100.0, 100.0)),
    ):
        atom = gemmi.Atom()
        atom.name = name
        atom.element = gemmi.Element(element)
        atom.pos = gemmi.Position(*pos)
        atom.occ = 1.0
        res.add_atom(atom)
    chain.add_residue(res)
    model.add_chain(chain)
    st.add_model(model)
    return st


def test_residue_points_is_the_heavy_atom_centroid_and_ignores_hydrogen():
    """The hydrogen sits 100 A away, so including it would be unmissable.

    Hydrogen presence depends on method and depositor, so a centroid that moved
    with it would not be comparable between two structures of the same protein.
    """
    points = residue_points(_one_residue_structure())
    assert points == {K("A", 201): pytest.approx((1.0, 2.0, 0.0))}


def test_residue_names_keys_by_author_numbering():
    assert residue_names(_one_residue_structure()) == {K("A", 201): "LEU"}


# ---------------------------------------------------------------------------
# rank_patches
# ---------------------------------------------------------------------------


def test_rank_patches_orders_by_descending_score():
    low = make_patch((K("A", 1), K("A", 2)))
    high = make_patch((K("A", 3), K("A", 4)))
    ranked = rank_patches(
        [low, high],
        {K("A", 1): 0.1, K("A", 2): 0.1, K("A", 3): 0.9, K("A", 4): 0.9},
        predictor_name="test",
    )
    assert [r.patch for r in ranked] == [high, low]
    assert ranked[0].score == pytest.approx(0.9)
    assert all(r.predictor == "test" for r in ranked)


def test_rank_patches_mean_does_not_reward_a_patch_for_being_large():
    """A sum would rank the big patch first on size alone; mean does not."""
    big = make_patch(tuple(K("A", i) for i in range(1, 7)))
    small = make_patch((K("A", 7), K("A", 8)))
    # 6 x 0.4 sums higher than 2 x 0.9 but means lower, which is the whole point.
    scores = {K("A", i): 0.4 for i in range(1, 7)} | {K("A", 7): 0.9, K("A", 8): 0.9}
    assert rank_patches(
        [big, small], scores, predictor_name="t"
    )[0].patch is small
    assert rank_patches(
        [big, small], scores, predictor_name="t", aggregate="sum"
    )[0].patch is big


def test_rank_patches_breaks_score_ties_on_area_then_residue_order():
    """Equal score: larger area first. Equal area too: canonical residue order."""
    scores = {K("A", i): 0.5 for i in range(1, 7)}
    small_area = make_patch((K("A", 1), K("A", 2)), area=10.0)
    big_area = make_patch((K("A", 3), K("A", 4)), area=99.0)
    ranked = rank_patches([small_area, big_area], scores, predictor_name="t")
    assert [r.patch for r in ranked] == [big_area, small_area]

    later = make_patch((K("A", 5), K("A", 6)), area=10.0)
    earlier = make_patch((K("A", 1), K("A", 2)), area=10.0)
    ranked = rank_patches([later, earlier], scores, predictor_name="t")
    assert [r.patch for r in ranked] == [earlier, later]


def test_rank_patches_is_deterministic_under_input_reordering():
    """Same patches in any input order must give the same output order."""
    patches = [
        make_patch((K("A", 1), K("A", 2)), area=10.0),
        make_patch((K("A", 3), K("A", 4)), area=10.0),
        make_patch((K("A", 5), K("A", 6)), area=10.0),
        make_patch((K("B", 1), K("B", 2)), area=10.0),
    ]
    scores = {k: 0.5 for p in patches for k in p.residues}
    forward = rank_patches(patches, scores, predictor_name="t")
    backward = rank_patches(list(reversed(patches)), scores, predictor_name="t")
    assert [r.patch.residues for r in forward] == [r.patch.residues for r in backward]


def test_rank_patches_components_sum_to_the_score_under_a_linear_aggregate():
    patch = make_patch((K("A", 1), K("A", 2)))
    components = {
        K("A", 1): {"exposure": 0.4, "concavity": 0.1},
        K("A", 2): {"exposure": 0.2, "concavity": 0.3},
    }
    scores = {k: sum(v.values()) for k, v in components.items()}
    scored = rank_patches(
        [patch], scores, predictor_name="t", residue_components=components
    )[0]
    assert sum(scored.components.values()) == pytest.approx(scored.score)
    assert scored.components["exposure"] == pytest.approx(0.3)
    assert scored.components["concavity"] == pytest.approx(0.2)


def test_rank_patches_components_default_to_empty():
    scored = rank_patches(
        [make_patch((K("A", 1),))], {K("A", 1): 0.5}, predictor_name="t"
    )[0]
    assert scored.components == {}


def test_rank_patches_rejects_an_unknown_aggregate():
    with pytest.raises(ValueError, match="aggregate must be one of"):
        rank_patches(
            [make_patch((K("A", 1),))],
            {K("A", 1): 0.5},
            predictor_name="t",
            aggregate="median",
        )


def test_rank_patches_raises_naming_the_unscored_residues():
    """An unscored patch residue means the two inputs disagree about numbering.

    Filling it with zero would rank the patch low for a bookkeeping reason that
    looks exactly like a structural one.
    """
    with pytest.raises(KeyError, match="A42"):
        rank_patches(
            [make_patch((K("A", 1), K("A", 42)))],
            {K("A", 1): 0.5},
            predictor_name="t",
        )


def test_rank_patches_rejects_an_empty_patch():
    with pytest.raises(ValueError, match="no residues"):
        rank_patches([make_patch(())], {}, predictor_name="t")


def test_scored_patch_to_dict_is_json_serialisable():
    scored = ScoredPatch(
        patch=make_patch((K("A", 1),)),
        score=0.5,
        components={"exposure": 0.5},
        predictor="t",
    )
    assert json.loads(json.dumps(scored.to_dict()))["residues"] == ["A1"]


# ---------------------------------------------------------------------------
# GeometricPredictor
# ---------------------------------------------------------------------------


def test_geometric_predictor_rejects_an_unknown_weight_name():
    """A typo'd weight that silently does nothing looks like a weight that
    had no effect, so it is refused rather than ignored."""
    with pytest.raises(ValueError, match="unknown feature weight"):
        GeometricPredictor(weights={"concavity": 1.0, "concavty": 1.0})


def test_default_weights_cover_every_feature_and_sum_to_one():
    assert set(DEFAULT_WEIGHTS) == set(FEATURE_NAMES)
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_geometric_predictor_scores_are_the_sum_of_its_components(
    cif_with_unobs_category,
):
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    predictor = GeometricPredictor()
    components = predictor.score_components(target, profile)
    scores = predictor.score_residues(target, profile)
    assert set(scores) == set(profile.relative_sasa)
    for key, score in scores.items():
        assert score == pytest.approx(sum(components[key].values()))


def test_geometric_predictor_components_are_weight_applied(cif_with_unobs_category):
    """Components already carry the weights, so an explanation cannot be
    rendered with a different set than the one that produced the ranking."""
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    zeroed = GeometricPredictor(weights={"exposure": 0.0, "concavity": 0.0})
    for components in zeroed.score_components(target, profile).values():
        assert components["exposure"] == 0.0
        assert components["hydrophobicity"] == 0.0


def test_geometric_predictor_name_is_recorded(cif_with_unobs_category):
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    predictor = GeometricPredictor()
    patches = [make_patch(tuple(sorted(profile.relative_sasa)[:2]))]
    ranked = rank_patches(
        patches,
        predictor.score_residues(target, profile),
        predictor_name=predictor.name,
    )
    assert ranked[0].predictor == "geometric"


# ---------------------------------------------------------------------------
# ExternalPredictor: loading
# ---------------------------------------------------------------------------


def test_external_csv_with_header_loads(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nC,325,0.81\nC,326,0.42\n")
    assert load_external_scores(path) == {
        K("C", 325): pytest.approx(0.81),
        K("C", 326): pytest.approx(0.42),
    }


def test_external_csv_column_aliases_and_ordering(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("probability,auth_seq_id,auth_asym_id\n0.7,12,B\n")
    assert load_external_scores(path) == {K("B", 12): pytest.approx(0.7)}


def test_external_tsv_without_header_is_positional(tmp_path: Path):
    path = tmp_path / "scores.tsv"
    path.write_text("C\t325\t0.81\nC\t326\t0.42\n")
    assert load_external_scores(path) == {
        K("C", 325): pytest.approx(0.81),
        K("C", 326): pytest.approx(0.42),
    }


def test_external_two_column_form_uses_combined_residue_tokens(tmp_path: Path):
    """Two columns means 'A325,score'; a chainless number is refused below."""
    path = tmp_path / "scores.csv"
    path.write_text("C325,0.81\nC52A,0.4\n")
    assert load_external_scores(path) == {
        K("C", 325): pytest.approx(0.81),
        K("C", 52, "A"): pytest.approx(0.4),
    }


def test_external_csv_skips_comments_and_blank_lines(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text(
        "# produced by some-predictor v1\n\nchain,resnum,score\nC,325,0.8\n"
    )
    assert load_external_scores(path) == {K("C", 325): pytest.approx(0.8)}


def test_external_json_array_of_objects_loads(tmp_path: Path):
    path = tmp_path / "scores.json"
    path.write_text(
        json.dumps(
            [
                {"chain": "C", "resnum": 325, "score": 0.81},
                {"chain": "C", "resnum": 52, "score": 0.4, "icode": "A"},
            ]
        )
    )
    assert load_external_scores(path) == {
        K("C", 325): pytest.approx(0.81),
        K("C", 52, "A"): pytest.approx(0.4),
    }


# ---------------------------------------------------------------------------
# ExternalPredictor: malformed input gives an actionable error
# ---------------------------------------------------------------------------


def test_external_bare_residue_number_is_refused(tmp_path: Path):
    """A number with no chain is the ambiguity this package exists to stop."""
    path = tmp_path / "scores.csv"
    path.write_text("325,0.81\n")
    with pytest.raises(ExternalScoreError, match="chain"):
        load_external_scores(path)


def test_external_label_seq_id_column_is_refused_by_name(tmp_path: Path):
    """label_seq_id read as an author number loads cleanly and aims wrong."""
    path = tmp_path / "scores.csv"
    path.write_text("chain,label_seq_id,score\nC,25,0.81\n")
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "author numbering" in str(exc.value)


def test_external_non_numeric_score_names_the_line(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nC,325,high\n")
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "line 2" in str(exc.value) and "'high'" in str(exc.value)


def test_external_unidentifiable_column_count_names_the_expected_columns(
    tmp_path: Path,
):
    path = tmp_path / "scores.csv"
    path.write_text("C,325,0.8,extra,more\n")
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "chain,resnum,score" in str(exc.value)


def test_external_ragged_row_names_the_line(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nC,325,0.8\nC,326\n")
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "line 3" in str(exc.value)


def test_external_duplicate_residue_with_two_scores_is_refused(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nC,325,0.8\nC,325,0.2\n")
    with pytest.raises(ExternalScoreError, match="ambiguous"):
        load_external_scores(path)


def test_external_malformed_json_gives_an_actionable_error_not_a_traceback(
    tmp_path: Path,
):
    path = tmp_path / "scores.json"
    path.write_text("{not json")
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "top-level JSON array" in str(exc.value)


def test_external_json_object_at_top_level_is_refused(tmp_path: Path):
    path = tmp_path / "scores.json"
    path.write_text(json.dumps({"C325": 0.8}))
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "not a list" in str(exc.value)


def test_external_json_record_missing_a_field_names_what_it_needs(tmp_path: Path):
    path = tmp_path / "scores.json"
    path.write_text(json.dumps([{"chain": "C", "score": 0.8}]))
    with pytest.raises(ExternalScoreError) as exc:
        load_external_scores(path)
    assert "residue number" in str(exc.value)


def test_external_empty_file_is_refused(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("")
    with pytest.raises(ExternalScoreError, match="empty"):
        load_external_scores(path)


def test_external_missing_file_says_so(tmp_path: Path):
    with pytest.raises(ExternalScoreError, match="no such score file"):
        load_external_scores(tmp_path / "absent.csv")


def test_external_url_is_refused_because_nothing_is_downloaded():
    """The adapter reads files the user produced; it never fetches.

    The predictors it hosts carry licences that forbid us redistributing their
    code, weights or output, so there is no fetch path at all.
    """
    with pytest.raises(ExternalScoreError, match="never downloads"):
        load_external_scores("https://example.org/scores.csv")


def test_external_predictor_needs_a_name(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nA,101,0.8\n")
    with pytest.raises(ValueError, match="needs a name"):
        ExternalPredictor("", path)


# ---------------------------------------------------------------------------
# ExternalPredictor: the numbering-mismatch warning
# ---------------------------------------------------------------------------


def test_external_scores_matching_the_structure_do_not_warn(
    cif_with_unobs_category, tmp_path: Path
):
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    path = tmp_path / "good.csv"
    path.write_text("chain,resnum,score\nA,101,0.9\nA,102,0.8\nA,103,0.7\n")
    predictor = ExternalPredictor("fake-tool", path)

    with warnings.catch_warnings():
        warnings.simplefilter("error", LowResidueMatchWarning)
        scores = predictor.score_residues(target, profile)
    # 0.9 was the top of three, so its percentile is 1.0.
    assert scores[K("A", 101)] == pytest.approx(1.0)
    assert predictor.raw[K("A", 101)] == pytest.approx(0.9)
    # LEFT join: every profiled residue is present, uncovered ones as NaN.
    assert set(scores) == set(profile.relative_sasa)
    assert math.isnan(scores[K("A", 106)])
    assert predictor.coverage(profile) == (3, 4)


def test_external_scores_in_the_wrong_numbering_scheme_warn_with_counts(
    cif_with_unobs_category, tmp_path: Path
):
    """The fixture's author numbers are label_seq + 100.

    So a file keyed by label_seq_id - 1, 2, 3 instead of 101, 102, 103 - is the
    real mistake, and it is silent: every lookup misses, every score defaults to
    zero and the ranking comes out plausible and wrong.
    """
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    path = tmp_path / "label_seq.csv"
    path.write_text("chain,resnum,score\nA,1,0.9\nA,2,0.8\nA,3,0.7\nA,6,0.6\n")
    predictor = ExternalPredictor("fake-tool", path)

    with pytest.warns(LowResidueMatchWarning) as record:
        scores = predictor.score_residues(target, profile)
    message = str(record[0].message)
    assert "0 of 4" in message
    assert "numbering-scheme mismatch" in message
    # NaN, not 0.0: an uncovered residue is unmeasured, not a bad site.
    assert all(math.isnan(v) for v in scores.values())
    assert predictor.coverage(profile) == (0, 4)


def test_external_partial_coverage_above_the_threshold_does_not_warn(
    cif_with_unobs_category, tmp_path: Path
):
    """Three of four present is above MIN_MATCH_FRACTION, so it is not a
    numbering failure - just a predictor that scored fewer residues."""
    assert MIN_MATCH_FRACTION == 0.5
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    path = tmp_path / "partial.csv"
    path.write_text("chain,resnum,score\nA,101,0.9\nA,102,0.8\nA,103,0.7\nA,999,0.6\n")
    predictor = ExternalPredictor("fake-tool", path)

    with warnings.catch_warnings():
        warnings.simplefilter("error", LowResidueMatchWarning)
        scores = predictor.score_residues(target, profile)
    assert math.isnan(scores[K("A", 106)])


def test_external_predictor_scores_feed_rank_patches(
    cif_with_unobs_category, tmp_path: Path
):
    """The whole point of the adapter: a file becomes a ranking."""
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nA,101,0.1\nA,102,0.1\nA,103,0.9\nA,106,0.9\n")
    predictor = ExternalPredictor("fake-tool", path)
    ranked = rank_patches(
        [
            make_patch((K("A", 101), K("A", 102))),
            make_patch((K("A", 103), K("A", 106))),
        ],
        predictor.score_residues(target, profile),
        predictor_name=predictor.name,
    )
    # Percentiles are monotone in the raw scores, so the ordering is unchanged
    # even though the values are not the file's.
    assert ranked[0].patch.residues == (K("A", 103), K("A", 106))
    assert ranked[0].score > ranked[1].score
    assert ranked[0].predictor == "fake-tool"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """Stands in for importlib.metadata.EntryPoint.

    Injected through PredictorRegistry(entry_points=...) rather than
    monkeypatched over importlib.metadata, so nothing process-wide is touched.
    """

    def __init__(self, name, value, factory=None, error=None):
        self.name = name
        self.value = value
        self._factory = factory
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._factory


def make_registry(entries=()) -> PredictorRegistry:
    """A registry of this test's own, with built-ins and no real plugin scan.

    Every registry test builds one of these instead of mutating
    DEFAULT_REGISTRY. A module-level dict would make the suite order-dependent:
    a backend registered by one test would still be registered for the next,
    and a fake entry point from this file would leak into another file's run -
    a failure that shows up only when the full suite runs in a different order
    than it did locally.
    """
    return PredictorRegistry(entry_points=lambda: list(entries))


@pytest.fixture(autouse=True)
def default_registry_is_left_untouched():
    """Fail any test in this file that mutates the process-wide registry.

    Autouse and asserting rather than merely restoring, because silently
    undoing a leak hides the leak. If a future test reaches for
    ``registry.register`` instead of :func:`make_registry`, this says so.
    """
    before = registry.snapshot()
    yield
    after = registry.snapshot()
    try:
        # Registrations only. The second element is the scan cache flag, which
        # any available()/get() call legitimately flips; that is a cache, not a
        # leak. A changed factory *mapping* is the leak, and restore() below
        # puts the flag back regardless.
        assert after[0] == before[0], (
            "this test mutated predict.registry.DEFAULT_REGISTRY's "
            "registrations; build your own with make_registry() instead of "
            "using the module-level functions"
        )
    finally:
        registry.restore(before)


def test_builtin_predictors_are_registered_eagerly():
    assert make_registry().available() == ["external", "geometric"]


def test_the_module_level_functions_see_the_builtins():
    """The convenience API must work, not just the class."""
    assert "geometric" in registry.available()
    assert isinstance(registry.get("geometric"), GeometricPredictor)


def test_get_geometric_returns_the_baseline():
    predictor = make_registry().get("geometric")
    assert isinstance(predictor, GeometricPredictor)
    assert predictor.name == "geometric"


def test_get_external_passes_through_the_path(tmp_path: Path):
    path = tmp_path / "scores.csv"
    path.write_text("chain,resnum,score\nA,101,0.8\n")
    predictor = make_registry().get("external", path=str(path), name="fake-tool")
    assert isinstance(predictor, ExternalPredictor)
    assert predictor.name == "fake-tool"
    # .raw is what the file said; .scores is percentile-normalised, and a lone
    # value has no distribution to sit in, so it is 0.5 rather than 1.0.
    assert predictor.raw == {K("A", 101): pytest.approx(0.8)}
    assert predictor.scores == {K("A", 101): pytest.approx(0.5)}


def test_get_unknown_name_lists_the_available_ones():
    with pytest.raises(UnknownPredictorError) as exc:
        make_registry().get("geomtric")
    assert "geometric" in str(exc.value) and "external" in str(exc.value)


def test_register_infers_the_name_from_the_factory():
    class Fake:
        name = "fake"

        def score_residues(self, target, profile):
            return {}

    reg = make_registry()
    assert reg.register(Fake) == "fake"
    assert isinstance(reg.get("fake"), Fake)


def test_register_refuses_to_shadow_an_existing_name():
    class Fake:
        name = "geometric"

    reg = make_registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.register(Fake)
    assert reg.register(Fake, replace=True) == "geometric"


def test_register_without_an_inferable_name_says_to_pass_one():
    """The regex is the implementation's exact wording, not a loosened one.

    A pattern that does not match its own message is a test that starts
    passing for the wrong reason the moment someone widens it.
    """
    with pytest.raises(ValueError, match=r"Pass name= explicitly\."):
        make_registry().register(lambda: None)


def test_two_registries_do_not_share_registrations():
    """The property the whole class exists for."""
    class Fake:
        name = "fake"

    first, second = make_registry(), make_registry()
    first.register(Fake)
    assert "fake" in first.available()
    assert "fake" not in second.available()


def test_entry_point_registered_backend_is_discovered():
    class Plugin:
        name = "plugin-predictor"

        def score_residues(self, target, profile):
            return {}

    reg = make_registry([_FakeEntryPoint("plugin-predictor", "pkg:Plugin", Plugin)])
    assert "plugin-predictor" in reg.available()
    assert isinstance(reg.get("plugin-predictor"), Plugin)


def test_a_broken_plugin_warns_and_leaves_the_builtins_working():
    """A plugin that cannot import must not take the whole tool down."""
    reg = make_registry(
        [_FakeEntryPoint("broken", "pkg:Missing", error=ImportError("no module"))]
    )
    with pytest.warns(PredictorPluginWarning, match="failed to load"):
        names = reg.available()
    assert "broken" not in names
    assert "geometric" in names


def test_a_plugin_cannot_silently_shadow_a_builtin():
    """Letting it through would change what a published run name means."""

    class Impostor:
        name = "geometric"

    reg = make_registry([_FakeEntryPoint("geometric", "pkg:Impostor", Impostor)])
    with pytest.warns(PredictorPluginWarning, match="already registered"):
        names = reg.available()
    assert names == ["external", "geometric"]
    assert isinstance(reg.get("geometric"), GeometricPredictor)


def test_refresh_picks_up_a_plugin_installed_after_the_first_scan():
    """The scan is cached, so a late plugin needs refresh() to be seen."""
    class Plugin:
        name = "late"

    entries: list[_FakeEntryPoint] = []
    reg = PredictorRegistry(entry_points=lambda: list(entries))
    assert "late" not in reg.available()

    entries.append(_FakeEntryPoint("late", "pkg:Plugin", Plugin))
    assert "late" not in reg.available(), "the scan should still be cached"
    reg.refresh()
    assert "late" in reg.available()


# ---------------------------------------------------------------------------
# The one real-structure test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chain_c_assembly_profile(real_6f5j):
    """Chain C of 6F5J, burial measured on the trimmed biological assembly.

    The trimmed structure is returned alongside the profile and is what the
    patches are grown on. Enumerating on the asymmetric unit instead would
    reach the same answer here, because chain C's own coordinates are the
    identity copy — but only by luck, and relying on that is the context
    confusion this package exists to catch.
    """
    target = load_target(real_6f5j)
    reference = reference_max_sasa(target.st)
    trimmed = trim_to_neighbourhood(expand_assembly(target), "C")
    profile = compute_burial(
        trimmed, context="assembly", focus_chain="C", reference=reference
    )
    return target, trimmed, profile


@pytest.mark.network
def test_known_binder_epitope_ranks_in_the_top_quartile_on_6f5j(
    chain_c_assembly_profile,
):
    """6F5J chain C 325/326 is a real binder's epitope: KD 604 nM, replicated.

    The assertion is top-quartile and not rank 1 on purpose. This is **n = 1**
    — one epitope, one target, one binder — and a stronger claim could not be
    supported by it. Site ranking is published prior art and this baseline is
    not competitive with a trained predictor; what this test establishes is only
    that the baseline is not anti-correlated with the one piece of ground truth
    we own. Tightening it to rank 1 would encode an overclaim, and tuning the
    weights until it passed at rank 1 would be fitting to the test set.
    """
    target, trimmed, profile = chain_c_assembly_profile
    patches = enumerate_patches(trimmed, profile, chain="C")
    assert patches, "no patches enumerated on 6F5J chain C"

    # NMS on, which is the default and the only setting under which a rank is
    # interpretable: enumerate_patches grows one patch per seed, so without
    # suppression the denominator counts near-duplicates rather than sites.
    ranked = GeometricPredictor().rank(target, profile, patches)
    assert len(ranked) < len(patches), "suppression removed nothing"

    epitope = {K("C", 325), K("C", 326)}
    cutoff = max(1, len(ranked) // 4)

    # Measured 2026-10-05 on 393 surface residues.
    #   pre-NMS:  114 patches, cutoff 28, either at 6,  both at 16
    #   post-NMS:  49 patches, cutoff 12, either at 3,  both at 7
    # The post-NMS numbers are the honest ones and are what is asserted.
    # Recorded so that a future drift can be told from an outright regression.
    contains_either = lambda residues: bool(epitope & residues)  # noqa: E731
    contains_both = lambda residues: epitope <= residues  # noqa: E731

    for label, holds in (("either", contains_either), ("both", contains_both)):
        matches = [
            i + 1 for i, r in enumerate(ranked) if holds(set(r.patch.residues))
        ]
        assert matches, (
            f"no patch among {len(ranked)} contains {label} of C325/C326; "
            f"the epitope residues are not on the enumerated surface"
        )
        assert matches[0] <= cutoff, (
            f"best patch containing {label} of C325/C326 ranked {matches[0]} "
            f"of {len(ranked)}, outside the top quartile (cutoff {cutoff})"
        )

    # The breakdown must stay honest on real data too, not only on fixtures.
    top = ranked[0]
    assert sum(top.components.values()) == pytest.approx(top.score)

    # And every result must carry gateable anchors with full coverage, since
    # the geometric baseline needs no external prior.
    best = ranked[min(matches) - 1]
    assert best.anchors
    assert best.n_covered == len(best.patch.residues)
    assert best.anchor_mean is not None and not math.isnan(best.anchor_mean)
    assert best.anchor_mean <= best.anchor_max


# ---------------------------------------------------------------------------
# Header-name parsing (the DiscoTope-3.0 stale-README hazard)
# ---------------------------------------------------------------------------


DISCOTOPE_HEADER = (
    "pdb,res_id,residue,rsa,alphafold_disordered,calibrated_score,epitope"
)


def test_discotope_shaped_csv_loads_by_header_name(tmp_path: Path):
    """DiscoTope emits no chain column; the chain is the suffix of `pdb`."""
    path = tmp_path / "discotope.csv"
    path.write_text(
        f"{DISCOTOPE_HEADER}\n"
        "7lj8_C,325,TYR,0.41,0,1.73,1\n"
        "7lj8_C,326,ASP,0.52,0,0.21,0\n"
    )
    loaded = load_external_score_file(path)
    assert loaded.score_column == "calibrated_score"
    assert loaded.raw == {
        K("C", 325): pytest.approx(1.73),
        K("C", 326): pytest.approx(0.21),
    }


def test_score_column_is_chosen_by_name_not_by_position(tmp_path: Path):
    """PIN. Index parsing would read `rsa`; name parsing reads the prediction.

    DiscoTope-3.0's README column list is stale - main.py inserts
    calibrated_score - so any fixed index is wrong for some version of the
    tool. These two files hold the SAME data with the columns permuted; a
    positional reader would return different numbers for them.
    """
    first = tmp_path / "a.csv"
    first.write_text(
        "pdb,res_id,calibrated_score,rsa\n7lj8_C,325,1.73,0.41\n7lj8_C,326,0.21,0.52\n"
    )
    second = tmp_path / "b.csv"
    second.write_text(
        "rsa,calibrated_score,res_id,pdb\n0.41,1.73,325,7lj8_C\n0.52,0.21,326,7lj8_C\n"
    )
    assert load_external_scores(first) == load_external_scores(second)
    # And the value read is the prediction, not the RSA that shares the row.
    assert load_external_scores(second)[K("C", 325)] == pytest.approx(1.73)


def test_calibrated_score_wins_over_a_raw_score_column(tmp_path: Path):
    """Both present means two different quantities; preference decides."""
    path = tmp_path / "both.csv"
    path.write_text("chain,resnum,score,calibrated_score\nC,325,0.11,1.73\n")
    loaded = load_external_score_file(path)
    assert loaded.score_column == "calibrated_score"
    assert loaded.raw[K("C", 325)] == pytest.approx(1.73)


def test_a_residue_type_column_is_not_mistaken_for_a_residue_key(tmp_path: Path):
    """DiscoTope's `residue` column holds TYR, not A325."""
    path = tmp_path / "typed.csv"
    path.write_text("pdb,res_id,residue,calibrated_score\n7lj8_C,325,TYR,1.73\n")
    assert load_external_scores(path) == {K("C", 325): pytest.approx(1.73)}


def test_a_malformed_pdb_column_is_refused_not_used_whole(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("pdb,res_id,calibrated_score\n7lj8,325,1.73\n")
    with pytest.raises(ExternalScoreError, match="<entry>_<chain>"):
        load_external_scores(path)


def test_a_scored_file_with_no_chain_anywhere_is_refused(tmp_path: Path):
    path = tmp_path / "nochain.csv"
    path.write_text("res_id,calibrated_score\n325,1.73\n")
    with pytest.raises(ExternalScoreError, match="no chain"):
        load_external_scores(path)


def test_discotope_shaped_json_loads(tmp_path: Path):
    path = tmp_path / "dt.json"
    path.write_text(
        json.dumps([{"pdb": "7lj8_C", "res_id": 325, "calibrated_score": 1.73}])
    )
    assert load_external_scores(path) == {K("C", 325): pytest.approx(1.73)}


# ---------------------------------------------------------------------------
# Midrank percentiles
# ---------------------------------------------------------------------------


def test_midrank_percentiles_span_zero_to_one():
    scores = {K("A", i): float(i) for i in (1, 2, 3, 4, 5)}
    out = midrank_percentiles(scores)
    assert out[K("A", 1)] == pytest.approx(0.0)
    assert out[K("A", 3)] == pytest.approx(0.5)
    assert out[K("A", 5)] == pytest.approx(1.0)


def test_midrank_percentiles_give_ties_their_mean_rank():
    """Ties share a rank rather than being broken arbitrarily.

    Tools round, and some emit identical scores across a whole loop; ordinal
    ranking would invent an ordering the predictor never expressed.
    """
    scores = {K("A", 1): 0.1, K("A", 2): 0.5, K("A", 3): 0.5, K("A", 4): 0.9}
    out = midrank_percentiles(scores)
    assert out[K("A", 2)] == pytest.approx(out[K("A", 3)])
    # 0-based ranks 1 and 2 share midrank 1.5, over n-1 = 3.
    assert out[K("A", 2)] == pytest.approx(0.5)


def test_midrank_percentiles_make_two_incommensurable_scales_comparable():
    """The reason this exists: raw values from these tools are not comparable.

    An unbounded z-like calibrated_score and a probability with a 0.1512
    threshold describe the same ordering of the same residues here, and after
    normalisation they agree exactly - which raw averaging would not.
    """
    z_like = {K("A", 1): -2.4, K("A", 2): 0.3, K("A", 3): 11.8}
    probability = {K("A", 1): 0.02, K("A", 2): 0.14, K("A", 3): 0.97}
    assert midrank_percentiles(z_like) == pytest.approx(
        midrank_percentiles(probability)
    )


def test_midrank_percentiles_keep_nan_out_of_the_ranking():
    scores = {K("A", 1): 0.1, K("A", 2): UNSCORED, K("A", 3): 0.9}
    out = midrank_percentiles(scores)
    assert math.isnan(out[K("A", 2)])
    assert out[K("A", 1)] == pytest.approx(0.0)
    assert out[K("A", 3)] == pytest.approx(1.0)


def test_midrank_percentiles_of_one_value_is_a_half_not_one():
    """A lone value receives the neutral midpoint percentile."""
    assert midrank_percentiles({K("A", 1): 7.0}) == {K("A", 1): pytest.approx(0.5)}


def test_midrank_percentiles_of_nothing_is_empty():
    assert midrank_percentiles({}) == {}


# ---------------------------------------------------------------------------
# NaN handling: LEFT join, n_covered
# ---------------------------------------------------------------------------


def test_an_uncovered_residue_does_not_erase_its_patch():
    """PIN. NaN must be skipped, not propagated.

    An uncovered residue is a coverage gap in the prior, not a structural
    verdict on the site. Propagating would let one missing residue kill a patch
    that is otherwise well measured.
    """
    patch = make_patch((K("A", 1), K("A", 2), K("A", 3)))
    scores = {K("A", 1): 0.8, K("A", 2): UNSCORED, K("A", 3): 0.6}
    scored = rank_patches([patch], scores, predictor_name="t")[0]
    assert scored.score == pytest.approx(0.7)
    assert scored.n_covered == 2
    assert scored.coverage == pytest.approx(2 / 3)


def test_a_patch_with_no_coverage_at_all_scores_nan_and_sorts_last():
    covered = make_patch((K("A", 1),), area=1.0)
    uncovered = make_patch((K("A", 2),), area=999.0)
    scores = {K("A", 1): 0.1, K("A", 2): UNSCORED}
    ranked = rank_patches([uncovered, covered], scores, predictor_name="t")
    assert ranked[0].patch is covered
    assert math.isnan(ranked[1].score)
    assert ranked[1].n_covered == 0


def test_nan_scores_sort_deterministically_regardless_of_input_order():
    """`-nan` compares false against everything, so order must not depend on it."""
    patches = [make_patch((K("A", i),), area=10.0) for i in (1, 2, 3)]
    scores = {K("A", 1): UNSCORED, K("A", 2): UNSCORED, K("A", 3): UNSCORED}
    forward = rank_patches(patches, scores, predictor_name="t")
    backward = rank_patches(list(reversed(patches)), scores, predictor_name="t")
    assert [r.patch.residues for r in forward] == [
        r.patch.residues for r in backward
    ]


def test_to_dict_renders_nan_as_null_not_the_invalid_json_literal():
    scored = rank_patches(
        [make_patch((K("A", 1),))], {K("A", 1): UNSCORED}, predictor_name="t"
    )[0]
    text = json.dumps(scored.to_dict())
    assert "NaN" not in text
    assert json.loads(text)["score"] is None


# ---------------------------------------------------------------------------
# Non-maximum suppression
# ---------------------------------------------------------------------------


def test_jaccard_of_identical_and_disjoint_sets():
    a = (K("A", 1), K("A", 2))
    assert jaccard(a, a) == pytest.approx(1.0)
    assert jaccard(a, (K("A", 3), K("A", 4))) == pytest.approx(0.0)
    # Two of three shared: 2/4.
    assert jaccard((K("A", 1), K("A", 2)), (K("A", 2), K("A", 3))) == pytest.approx(
        1 / 3
    )


def test_nms_keeps_the_higher_scoring_member_of_an_overlapping_pair():
    keep = make_patch((K("A", 1), K("A", 2), K("A", 3), K("A", 4)))
    drop = make_patch((K("A", 1), K("A", 2), K("A", 3), K("A", 5)))
    scores = {K("A", i): 0.9 for i in (1, 2, 3, 4)} | {K("A", 5): 0.1}
    ranked = rank_patches([keep, drop], scores, predictor_name="t")
    assert jaccard(keep.residues, drop.residues) >= NMS_JACCARD_THRESHOLD
    kept = suppress_overlapping(ranked)
    assert [k.patch for k in kept] == [keep]


def test_nms_keeps_patches_below_the_overlap_threshold():
    a = make_patch((K("A", 1), K("A", 2), K("A", 3)))
    b = make_patch((K("A", 3), K("A", 4), K("A", 5)))
    scores = {K("A", i): 0.5 for i in range(1, 6)}
    assert jaccard(a.residues, b.residues) < NMS_JACCARD_THRESHOLD
    kept = suppress_overlapping(rank_patches([a, b], scores, predictor_name="t"))
    assert len(kept) == 2


def test_nms_rejects_a_zero_threshold_that_would_suppress_everything():
    with pytest.raises(ValueError, match="suppress every patch"):
        suppress_overlapping([], threshold=0.0)


# ---------------------------------------------------------------------------
# Anchors: mean is gateable, max is not
# ---------------------------------------------------------------------------


def test_anchors_are_the_exposed_hydrophobic_residues():
    patch = make_patch((K("A", 1), K("A", 2), K("A", 3)))
    profile = make_profile({K("A", 1): 0.6, K("A", 2): 0.6, K("A", 3): 0.6})
    names = {K("A", 1): "LEU", K("A", 2): "ASP", K("A", 3): "PHE"}
    assert anchor_residues(patch, profile, names) == (K("A", 1), K("A", 3))


def test_a_buried_hydrophobic_is_not_an_anchor():
    """Exposure is required: a buried residue is not gripped by anything."""
    patch = make_patch((K("A", 1), K("A", 2)))
    profile = make_profile({K("A", 1): 0.01, K("A", 2): 0.6})
    names = {K("A", 1): "LEU", K("A", 2): "PHE"}
    assert anchor_residues(patch, profile, names) == (K("A", 2),)


def test_an_all_polar_patch_falls_back_to_the_most_exposed_residues():
    """A polar site is legitimate and must not be silently ungateable."""
    patch = make_patch(tuple(K("A", i) for i in range(1, 6)))
    profile = make_profile({K("A", i): i / 10.0 for i in range(1, 6)})
    names = {K("A", i): "ASP" for i in range(1, 6)}
    anchors = anchor_residues(patch, profile, names)
    assert anchors == (K("A", 3), K("A", 4), K("A", 5))


def test_anchor_mean_not_max_is_what_a_gate_reads(cif_with_unobs_category):
    """PIN. One occluded rim residue must not kill an otherwise clean patch.

    On a per-patch MAX, a single partly-occluded residue decides the verdict,
    which mass-kills surface anywhere near an oligomer contact. The mean over
    anchors is what a gate or a delta must threshold on; the max is reported
    only for inspection and is named so in the output.
    """
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    patches = [make_patch(tuple(sorted(profile.relative_sasa)))]
    scored = GeometricPredictor().rank(target, profile, patches, nms=False)[0]

    assert scored.anchors
    assert scored.anchor_mean is not None and scored.anchor_max is not None
    assert scored.anchor_mean <= scored.anchor_max
    # The output names the max as un-gateable rather than leaving it to habit.
    assert "anchor_max_do_not_threshold" in scored.to_dict()


# ---------------------------------------------------------------------------
# The zero-external-dependency requirement, and the honesty block
# ---------------------------------------------------------------------------


def test_the_external_prior_default_weight_is_zero():
    """Hard requirement: no external file, GPU, Docker, web form or account."""
    assert EXTERNAL_PRIOR_DEFAULT_WEIGHT == 0.0
    assert "external" not in DEFAULT_WEIGHTS
    assert set(DEFAULT_WEIGHTS) == set(FEATURE_NAMES)


def test_a_complete_ranking_comes_from_a_structure_file_alone(
    cif_with_unobs_category,
):
    """The default path must need nothing but the structure.

    No score file is constructed anywhere in this test, so if the default
    predictor ever acquired a required external input this fails rather than
    degrading for the users least able to supply one.
    """
    target = load_target(cif_with_unobs_category)
    profile = compute_burial(target.st, context="chain", focus_chain="A")
    patches = [make_patch(tuple(sorted(profile.relative_sasa))[:3])]
    ranked = GeometricPredictor().rank(target, profile, patches)
    assert len(ranked) == 1
    assert not math.isnan(ranked[0].score)
    assert ranked[0].n_covered == 3


def test_provenance_states_zero_fitted_outcomes_unconditionally():
    block = provenance()
    assert block["n_outcomes_fitted"] == 0
    assert N_OUTCOMES_FITTED == 0
    assert block["weights_tuned"] is False
    assert block["trained_model"] is False
    assert block["site_ranking_is_prior_art"] is True
    assert json.loads(json.dumps(block))["n_outcomes_fitted"] == 0


def test_every_scored_patch_carries_the_fitted_outcome_count():
    scored = rank_patches(
        [make_patch((K("A", 1),))], {K("A", 1): 0.5}, predictor_name="t"
    )[0]
    assert scored.to_dict()["n_outcomes_fitted"] == 0
