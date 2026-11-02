import tempfile
import unittest
from dataclasses import replace

import numpy as np

from dynamics.ember.candidates import group_observations
from dynamics.ember.embeddings import EmbeddingCache, EmbeddingKey, extract_local_esm2
from dynamics.ember.execution import ComputeDisabled, ExecutionPolicy
from dynamics.ember.features import (
    ENSEMBLE_NAMES,
    STATIC_NAMES,
    FeatureNormalizer,
    ensemble_features,
    static_features,
)
from dynamics.ember.schema import Observation

HASH = "a" * 64


def obs(name, frame, source="ensemble", score=1.0, volume=None):
    return Observation(name, frame, source, (0, 1), (1.0, 2.0, 3.0), score, volume=volume)


class FeatureTests(unittest.TestCase):
    def test_ensemble_pooling_permutation_and_frame_dedup(self):
        observations = [
            obs("a", "f1", volume=10.0),
            obs("b", "f1", score=2.0, volume=20.0),
            obs("c", "f2", volume=40.0),
            obs("d", "apo", source="apo", volume=5.0),
        ]
        a = ensemble_features(group_observations(observations)[0], ("f1", "f2", "f3"))
        b = ensemble_features(group_observations(observations[::-1])[0], ("f3", "f2", "f1"))
        np.testing.assert_array_equal(a, b)
        self.assertEqual(a.shape, (len(ENSEMBLE_NAMES),))
        self.assertAlmostEqual(a[ENSEMBLE_NAMES.index("support_fraction")], 2 / 3)
        self.assertEqual(a[ENSEMBLE_NAMES.index("volume_mean")], 30.0)
        self.assertEqual(a[ENSEMBLE_NAMES.index("volume_change_from_apo")], 25.0)
        self.assertTrue(np.isnan(a[ENSEMBLE_NAMES.index("quality_mean")]))
        with self.assertRaisesRegex(ValueError, "unaccepted"):
            ensemble_features(group_observations(observations)[0], ("f1",))

    def test_static_features_independent_of_ensemble_observation_values(self):
        a = group_observations([obs("a", "apo", source="apo", volume=5.0), obs("b", "f1", volume=10.0)])[0]
        b = replace(a, observations=(a.observations[0], replace(a.observations[1], volume=100000.0)))
        xyz = np.array([[0.0, 0.0, 0.0], [3.8, 0.0, 0.0], [4.0, 3.0, 0.0], [0.0, 1.0, 2.0]])
        logits, mask = np.arange(4), np.ones(4, dtype=bool)
        fa = static_features(a, "ACDE", logits, xyz, mask)
        fb = static_features(b, "ACDE", logits, xyz, mask)
        np.testing.assert_array_equal(fa, fb)
        self.assertEqual(fa.shape, (len(STATIC_NAMES),))
        rotated = xyz @ np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]) + 20.0
        np.testing.assert_allclose(fa, static_features(a, "ACDE", logits, rotated, mask), rtol=1e-6)

    def test_normalization_is_train_only_protein_balanced_and_masked(self):
        first = np.array([[0.0, np.nan], [0.0, np.nan], [0.0, np.nan]])
        second = np.array([[10.0, 2.0]])
        norm = FeatureNormalizer.fit(
            [first, second],
            names=("a", "b"),
            target_ids=["t1", "t2"],
            partitions=["train"] * 2,
            split_sha256=HASH,
        )
        self.assertEqual(norm.mean, (5.0, 2.0))
        result = norm.transform(np.array([[np.nan, 2.0], [15.0, np.nan]]), names=("a", "b"))
        np.testing.assert_allclose(result, [[0.0, 0.0, 1.0, 0.0], [2.0, 0.0, 0.0, 1.0]])
        with self.assertRaisesRegex(ValueError, "training proteins only"):
            FeatureNormalizer.fit(
                [first], names=("a", "b"), target_ids=["test"], partitions=["test"], split_sha256=HASH
            )
        with self.assertRaisesRegex(ValueError, "ordering"):
            norm.transform(first, names=("b", "a"))

    def test_missing_apo_is_not_zero_pocket_volume(self):
        site = group_observations([obs("a", "f1", volume=10.0)])[0]
        f = ensemble_features(site, ("f1",))
        self.assertTrue(np.isnan(f[ENSEMBLE_NAMES.index("volume_change_from_apo")]))

    def test_unobserved_and_constant_training_columns_cannot_gain_spurious_effect(self):
        norm = FeatureNormalizer.fit(
            [np.array([[np.nan, 2.0], [np.nan, 2.0]])],
            names=("missing", "constant"),
            target_ids=["t1"],
            partitions=["train"],
            split_sha256=HASH,
        )
        transformed = norm.transform(np.array([[900.0, 100.0]]), names=("missing", "constant"))
        np.testing.assert_array_equal(transformed, [[0.0, 0.0, 1.0, 0.0]])


class CacheTests(unittest.TestCase):
    def test_content_addressing_corruption_and_immutability(self):
        key = EmbeddingKey("ACD", "fixture", HASH, HASH, HASH, width=2)
        array = np.arange(6).reshape(3, 2).astype(np.float32)
        with tempfile.TemporaryDirectory() as folder:
            cache = EmbeddingCache(folder)
            cache.store(key, array)
            np.testing.assert_array_equal(cache.load(key), array)
            with self.assertRaisesRegex(ValueError, "different embeddings"):
                cache.store(key, array + 1)
            other = replace(key, checkpoint_sha256="b" * 64)
            self.assertNotEqual(cache.paths(key), cache.paths(other))
            path, _ = cache.paths(key)
            with path.open("ab") as handle:
                handle.write(b"corruption")
            with self.assertRaisesRegex(ValueError, "checksum"):
                cache.load(key)

    def test_shape_and_special_tokens_are_not_silently_accepted(self):
        key = EmbeddingKey("ACD", "fixture", HASH, HASH, HASH, width=2)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "shape"):
                EmbeddingCache(folder).store(key, np.zeros((5, 2)))

    def test_default_execution_denied_before_model_import(self):
        with self.assertRaises(ComputeDisabled):
            extract_local_esm2("ACD", "/does/not/exist", policy=ExecutionPolicy())


if __name__ == "__main__":
    unittest.main()
