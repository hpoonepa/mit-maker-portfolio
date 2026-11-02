import json
import unittest

import numpy as np

from senba_sprint.metrics import analyze_records


def record(
    *,
    protein="p1",
    replica="r1",
    start_id="s1",
    training="t1",
    inference="i1",
    source=None,
    candidate=None,
    target=None,
):
    target = np.zeros((1, 3)) if target is None else np.asarray(target, dtype=float)
    source = np.zeros((2, len(target), 3)) if source is None else np.asarray(source, dtype=float)
    candidate = source.copy() if candidate is None else np.asarray(candidate, dtype=float)
    return {
        "protein_id": protein,
        "replica_id": replica,
        "start_id": start_id,
        "training_seed": training,
        "inference_seed": inference,
        "units": "angstrom",
        "alignment": "start_aligned",
        "start": np.zeros_like(target).tolist(),
        "target": target.tolist(),
        "source": source.tolist(),
        "candidate": candidate.tolist(),
    }


def metric(result, side="source"):
    return result["per_transition"][0][side]


class MetricsTests(unittest.TestCase):
    def test_mse_decomposition_identity_and_population_correction(self):
        samples = np.array([[[1.0, 0, 0]], [[3.0, 0, 0]]])
        got = metric(analyze_records([record(source=samples)], n_bootstrap=5))
        self.assertAlmostEqual(got["sample_mse"], 5.0)
        self.assertAlmostEqual(got["centroid_mse"], 4.0)
        self.assertAlmostEqual(got["ensemble_variance"], 1.0)
        self.assertAlmostEqual(got["mse_identity_residual"], 0.0)
        self.assertAlmostEqual(got["population_mean_mse_estimate"], 3.0)

    def test_common_translation_preserves_metrics(self):
        samples = np.array([[[1.0, 2, 0]], [[3.0, -1, 0]]])
        base = record(source=samples, candidate=samples + 0.5)
        shifted = json.loads(json.dumps(base))
        shift = np.array([7.0, -4.0, 2.0])
        for field in ("start", "target", "source", "candidate"):
            shifted[field] = (np.asarray(shifted[field]) + shift).tolist()
        one = analyze_records([base], n_bootstrap=5)
        two = analyze_records([shifted], n_bootstrap=5)
        for side in ("source", "candidate"):
            for name in ("sample_mse", "centroid_rmsd", "energy_score"):
                self.assertAlmostEqual(metric(one, side)[name], metric(two, side)[name])

    def test_energy_score_k2_analytic(self):
        samples = np.array([[[-1.0, 0, 0]], [[1.0, 0, 0]]])
        got = metric(analyze_records([record(source=samples)], n_bootstrap=5))
        self.assertAlmostEqual(got["mean_sample_rmsd"], 1.0)
        self.assertAlmostEqual(got["pairwise_rmsd"], 2.0)
        self.assertAlmostEqual(got["energy_score"], 0.0)
        self.assertAlmostEqual(got["population_mean_mse_estimate"], -1.0)

    def test_mse_collapse_counterexample(self):
        diverse = np.array([[[-1.0, 0, 0]], [[1.0, 0, 0]]])
        collapsed = np.array([[[1.0, 0, 0]], [[1.0, 0, 0]]])
        result = analyze_records(
            [record(source=diverse, candidate=collapsed)], n_bootstrap=5
        )
        self.assertAlmostEqual(metric(result, "source")["sample_mse"], 1.0)
        self.assertAlmostEqual(metric(result, "candidate")["sample_mse"], 1.0)
        self.assertLess(
            metric(result, "source")["energy_score"],
            metric(result, "candidate")["energy_score"],
        )

    def test_rejects_unequal_lengths(self):
        bad = record(candidate=np.zeros((3, 1, 3)))
        with self.assertRaisesRegex(ValueError, "same K"):
            analyze_records([bad])

    def test_rejects_non_finite_coordinates(self):
        bad = record()
        bad["target"][0][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            analyze_records([bad])

    def test_rejects_duplicate_full_id(self):
        first = record()
        with self.assertRaisesRegex(ValueError, "duplicate record ID"):
            analyze_records([first, dict(first)])

    def test_inference_repeats_are_averaged_before_transition_units(self):
        zero = np.zeros((2, 1, 3))
        two = np.full((2, 1, 3), [2.0, 0, 0])
        records = [
            record(inference="i1", source=zero, candidate=zero),
            record(inference="i2", source=zero, candidate=two),
            record(start_id="s2", inference="i1", source=zero, candidate=zero),
        ]
        result = analyze_records(records, n_bootstrap=5)
        protein = result["per_protein"][0]
        self.assertEqual(protein["n_transition_units"], 2)
        self.assertEqual(protein["n_records"], 3)
        self.assertAlmostEqual(protein["delta"]["sample_mse"], 1.0)

    def test_protein_macro_does_not_weight_by_transition_count(self):
        zero = np.zeros((2, 1, 3))
        two = np.full((2, 1, 3), [2.0, 0, 0])
        records = [record(protein="p1", source=zero, candidate=two)]
        records += [
            record(protein="p2", start_id=f"s{i}", source=zero, candidate=zero)
            for i in range(3)
        ]
        result = analyze_records(records, n_bootstrap=5)
        self.assertAlmostEqual(
            result["per_seed"][0]["protein_macro_delta"]["sample_mse"], 2.0
        )

    def test_rejects_unequal_proteins_across_training_seeds(self):
        records = [record(training="t1"), record(training="t2", protein="p2")]
        with self.assertRaisesRegex(ValueError, "unequal protein sets"):
            analyze_records(records)

    def test_rejects_inconsistent_transition_matching(self):
        records = [record(training="t1"), record(training="t2", start_id="s2")]
        with self.assertRaisesRegex(ValueError, "transition matching"):
            analyze_records(records)

    def test_reused_source_draw_must_be_identical_across_training_seeds(self):
        zero = np.zeros((2, 1, 3))
        one = np.ones((2, 1, 3))
        records = [
            record(training="t1", source=zero),
            record(training="t2", source=one),
        ]
        with self.assertRaisesRegex(ValueError, "source must be identical"):
            analyze_records(records)

    def test_distinct_inference_ids_allow_distinct_sources_between_seeds(self):
        zero = np.zeros((2, 1, 3))
        one = np.ones((2, 1, 3))
        records = [
            record(training="t1", inference="i1", source=zero),
            record(training="t2", inference="i2", source=one),
        ]
        result = analyze_records(records, n_bootstrap=5)
        self.assertEqual(result["run"]["n_training_seeds"], 2)

    def test_bootstrap_is_deterministic_and_json_serializable(self):
        zero = np.zeros((2, 1, 3))
        records = [
            record(protein=f"p{i}", source=zero, candidate=zero + i)
            for i in range(1, 4)
        ]
        first = analyze_records(records, n_bootstrap=100, random_seed=19)
        second = analyze_records(reversed(records), n_bootstrap=100, random_seed=19)
        self.assertEqual(first["bootstrap"], second["bootstrap"])
        json.dumps(first, allow_nan=False)

    def test_centroid_sensitivity_uses_all_small_k_subsets(self):
        samples = np.arange(12, dtype=float).reshape(4, 1, 3)
        got = metric(analyze_records([record(source=samples)], n_bootstrap=5))
        sensitivity = got["centroid_sensitivity"]
        self.assertEqual([row["k"] for row in sensitivity], [1, 2, 3, 4])
        self.assertEqual([row["n_subsets"] for row in sensitivity], [4, 6, 4, 1])
        self.assertTrue(all(row["exhaustive"] for row in sensitivity))


if __name__ == "__main__":
    unittest.main()
