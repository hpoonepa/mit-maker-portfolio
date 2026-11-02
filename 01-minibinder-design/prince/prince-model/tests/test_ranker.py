"""Check frozen inference against independently saved XGBoost probabilities."""
import copy
import json
from pathlib import Path

import pytest

from prince_ranker import feature_schema, rank_patches
from prince_ranker.inference import select_diverse

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def payload():
    return json.loads((ROOT / "examples/patches.json").read_text())


def test_schema_matches_saved_trees():
    model = json.loads((ROOT / "src/prince_ranker/data/site_ranker.json").read_text())
    schema = feature_schema()
    assert len(schema["feature_names"]) == int(model["learner"]["learner_model_param"]["num_feature"]) == 660
    assert len(set(schema["feature_names"])) == 660


def test_frozen_prediction_parity(payload):
    pytest.importorskip("xgboost")
    expected = json.loads((ROOT / "examples/expected.json").read_text())
    result = rank_patches(payload, top=10)
    assert result["patches_scored"] == len(expected["all_scores"])
    for patch in result["ranked"]:
        assert patch["score"] == pytest.approx(expected["all_scores"][patch["patch_index"]], abs=1e-6)
    # Each row must also score correctly when supplied on its own.
    for row, score in enumerate(expected["all_scores"]):
        one = dict(payload, features=[payload["features"][row]], patches=[payload["patches"][row]])
        assert rank_patches(one)["ranked"][0]["score"] == pytest.approx(score, abs=1e-6)


def test_nms_boundary_and_stable_ties():
    assert select_diverse([0.8, 0.8, 0.7], [["A1", "A2"], ["A1"], ["A3"]], 3) == [0, 2]
    assert select_diverse([0.8, 0.9], [["A1", "A2"], ["A1", "A3"]], 2) == [1, 0]


@pytest.mark.parametrize("top", [0, 11, True, 1.5, "3"])
def test_invalid_top(payload, top):
    with pytest.raises(ValueError, match="top"):
        rank_patches(payload, top)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("pca_id", "different-projection"),
    ("feature_names", ["wrong"] * 660), ("patches", []),
    ("patches", [["A1", "A1"]]), ("features", [[0.0] * 659]),
])
def test_invalid_contract(payload, field, value):
    invalid = copy.deepcopy(payload)
    invalid[field] = value
    with pytest.raises(ValueError):
        rank_patches(invalid)


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf")])
def test_invalid_feature(payload, value):
    pytest.importorskip("xgboost")
    payload["features"][0][0] = value
    with pytest.raises(ValueError):
        rank_patches(payload)
