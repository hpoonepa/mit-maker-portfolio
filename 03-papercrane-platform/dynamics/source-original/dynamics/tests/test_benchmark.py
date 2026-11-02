import pytest
from dynamics.benchmark import (
    is_hit,
    recovery_rate,
    compare_recovery,
)


def test_is_hit_within_threshold_true():
    assert is_hit(
        predicted=(0, 0, 0), ground_truth=(3.0, 0, 0), distance_threshold=5.0
    ) is True


def test_is_hit_outside_threshold_false():
    assert is_hit(
        predicted=(0, 0, 0), ground_truth=(6.0, 0, 0), distance_threshold=5.0
    ) is False


def test_recovery_rate_counts_target_as_hit_if_any_prediction_hits():
    per_target = [
        {"target": "a", "predictions": [(0, 0, 0), (10, 10, 10)],
         "ground_truth": (0.5, 0, 0)},                       # hit
        {"target": "b", "predictions": [(50, 50, 50)],
         "ground_truth": (0, 0, 0)},                          # miss
        {"target": "c", "predictions": [], "ground_truth": (0, 0, 0)},  # miss
    ]
    rate = recovery_rate(per_target, distance_threshold=5.0)
    assert rate == pytest.approx(1 / 3)


def test_recovery_rate_with_empty_input_is_zero():
    assert recovery_rate([], distance_threshold=5.0) == 0.0


def test_compare_recovery_yields_margin():
    ensemble = [
        {"target": "a", "predictions": [(0, 0, 0)], "ground_truth": (0, 0, 0)},
        {"target": "b", "predictions": [(0, 0, 0)], "ground_truth": (0, 0, 0)},
    ]
    static = [
        {"target": "a", "predictions": [(50, 50, 50)], "ground_truth": (0, 0, 0)},
        {"target": "b", "predictions": [(0, 0, 0)], "ground_truth": (0, 0, 0)},
    ]
    result = compare_recovery(ensemble, static, distance_threshold=5.0)
    assert result["ensemble_recovery"] == 1.0
    assert result["static_recovery"] == 0.5
    assert result["margin_pp"] == pytest.approx(50.0)


import json
from dynamics.aggregate import aggregate_results


def test_aggregate_results_returns_per_target_predictions_lists(tmp_path):
    csv = tmp_path / "pm.csv"
    csv.write_text("apo_pdb,holo_pdb,ligand_resname\nA,A2,LIG\nB,B2,LIG\n")
    j1 = tmp_path / "A.json"
    j1.write_text(json.dumps({
        "apo_pdb_id": "a",
        "num_frames": 10,
        "ensemble_sites": [],
        "apo_baseline_pockets": [{"center": [0, 0, 0], "volume": 50, "druggability": 0.5}],
        "cryptic_calls": [{"centroid": [1.0, 0, 0], "score": 0.8,
                            "persistence": 0.8, "apo_match_distance": 30.0}],
    }))
    j2 = tmp_path / "B.json"
    j2.write_text(json.dumps({
        "apo_pdb_id": "b",
        "num_frames": 10,
        "ensemble_sites": [],
        "apo_baseline_pockets": [],
        "cryptic_calls": [],
    }))
    holo_centroids = {"a": (0.0, 0.0, 0.0), "b": (0.0, 0.0, 0.0)}
    ensemble, static = aggregate_results(
        per_target_jsons=[j1, j2],
        holo_centroids=holo_centroids,
    )
    assert len(ensemble) == 2
    assert ensemble[0]["target"] == "a"
    assert ensemble[0]["predictions"] == [(1.0, 0.0, 0.0)]
    assert static[0]["predictions"] == [(0.0, 0.0, 0.0)]
    assert static[1]["predictions"] == []


def test_aggregate_results_skips_targets_with_no_centroid(tmp_path):
    import json as _json
    from dynamics.aggregate import aggregate_results
    j = tmp_path / "X.json"
    j.write_text(_json.dumps({
        "apo_pdb_id": "x",
        "num_frames": 5,
        "ensemble_sites": [],
        "apo_baseline_pockets": [],
        "cryptic_calls": [],
    }))
    # holo_centroids has no entry for "x" — target should be silently skipped
    ensemble, static = aggregate_results([j], holo_centroids={})
    assert ensemble == []
    assert static == []


def test_aggregate_results_handles_uppercase_target_id(tmp_path):
    import json as _json
    from dynamics.aggregate import aggregate_results
    j = tmp_path / "UPPER.json"
    j.write_text(_json.dumps({
        "apo_pdb_id": "ABCD",  # uppercase
        "num_frames": 5,
        "ensemble_sites": [],
        "apo_baseline_pockets": [],
        "cryptic_calls": [{"centroid": [1.0, 2.0, 3.0], "score": 0.5,
                            "persistence": 0.5, "apo_match_distance": 20.0}],
    }))
    # holo_centroids keyed lowercase — should still match after normalization
    ensemble, static = aggregate_results([j], holo_centroids={"abcd": (0.0, 0.0, 0.0)})
    assert len(ensemble) == 1
    assert ensemble[0]["predictions"] == [(1.0, 2.0, 3.0)]
