import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from senba_sprint.inference import _validate_inputs, kabsch_align, run_pair


class KabschTests(unittest.TestCase):
    def test_known_proper_rotation_and_translation(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 2., 0.], [0., 0., 3.]])
        rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        mobile = reference @ rotation.T + np.array([5., -2., 7.])
        aligned = kabsch_align(reference, mobile)
        np.testing.assert_allclose(aligned, reference, atol=1e-12)

    def test_vectorized_alignment(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        mobile = np.stack([reference + [3, 4, 5], reference + [-7, 1, 2]])
        np.testing.assert_allclose(
            kabsch_align(reference, mobile), np.broadcast_to(reference, mobile.shape), atol=1e-12
        )

    def test_reflection_is_not_used(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 2., 0.], [0., 0., 3.]])
        reflected = reference * np.array([-1., 1., 1.])
        aligned = kabsch_align(reference, reflected)
        self.assertGreater(np.sqrt(np.mean((aligned - reference) ** 2)), 0.1)


class InputTests(unittest.TestCase):
    def test_standard_masked_atoms_are_allowed(self):
        atom14 = np.ones((1, 14, 3), dtype=np.float32)
        atom14[0, 5:] = 0  # Alanine has five atoms.
        ids = {key: "x" for key in ("protein_id", "replica_id", "start_id", "training_seed", "inference_seed")}
        got = _validate_inputs(atom14, np.ones((1, 3)), "A", 2, 10, 8, ids)
        self.assertEqual(got[2], "A")

    def test_missing_real_atom_rejected(self):
        atom14 = np.ones((1, 14, 3), dtype=np.float32)
        atom14[0, 1] = 0
        ids = {key: "x" for key in ("protein_id", "replica_id", "start_id", "training_seed", "inference_seed")}
        with self.assertRaisesRegex(ValueError, "missing real atom"):
            _validate_inputs(atom14, np.ones((1, 3)), "A", 2, 10, 8, ids)

    def test_rejects_invalid_sampling_and_sequence(self):
        atom14 = np.ones((1, 14, 3), dtype=np.float32)
        ids = {key: "x" for key in ("protein_id", "replica_id", "start_id", "training_seed", "inference_seed")}
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _validate_inputs(atom14, np.ones((1, 3)), "X", 2, 10, 8, ids)
        with self.assertRaisesRegex(ValueError, "at least 2"):
            _validate_inputs(atom14, np.ones((1, 3)), "A", 1, 10, 8, ids)


class _Device(str):
    type = "cpu"


class _FakeCuda:
    @staticmethod
    def is_available():
        return False


class _FakeTorch:
    cuda = _FakeCuda()

    @staticmethod
    def device(value):
        return _Device(value)


class PairedAdapterTests(unittest.TestCase):
    def setUp(self):
        self.ids = {key: "id-" + key for key in (
            "protein_id", "replica_id", "start_id", "training_seed", "inference_seed"
        )}
        self.start = np.ones((3, 14, 3), dtype=np.float32)
        self.start[:, 1] = [[1, 1, 1], [2, 1, 1], [1, 2, 1]]
        self.target = self.start[:, 1] + [8, -3, 2]

    def test_mocked_contract_pairs_seeds_and_returns_metric_record(self):
        starts = self.start[:, 1]
        source = np.zeros((2, 3, 14, 3), dtype=np.float32)
        candidate = np.zeros_like(source)
        source[:, :, 1] = starts[None] + np.array([[4, 5, 6], [-3, 2, 1]])[:, None]
        candidate[:, :, 1] = starts[None] + np.array([[7, 1, -2], [2, -4, 3]])[:, None]
        loaded = []
        calls = []

        def fake_load(path, expected, device, torch, module):
            loaded.append((path, expected, str(device)))
            return object(), expected

        def fake_generate(model, batch, steps, torch, seed, device):
            calls.append((steps, seed, str(device)))
            return (source if len(calls) == 1 else candidate), "before", "after"

        with patch("senba_sprint.inference._torch_and_upstream", return_value=(_FakeTorch(), None, None, None, object(), None)), \
             patch("senba_sprint.inference._load_model", side_effect=fake_load), \
             patch("senba_sprint.inference.build_batch", return_value={}), \
             patch("senba_sprint.inference._generate", side_effect=fake_generate), \
             patch("senba_sprint.inference.Path.is_file", return_value=True):
            got = run_pair(self.start, self.target, "AAA", Path("source.ckpt"), Path("candidate.ckpt"),
                           "a" * 64, "b" * 64, samples=2, ode_steps=10, seed=19, ids=self.ids)

        self.assertEqual(got["record"]["alignment"], "start_aligned")
        self.assertEqual({key: got["record"][key] for key in self.ids}, self.ids)
        self.assertEqual(calls, [(10, 19, "cpu"), (10, 19, "cpu")])
        self.assertEqual([item[1] for item in loaded], ["a" * 64, "b" * 64])
        np.testing.assert_allclose(got["record"]["target"], starts, atol=1e-6)
        np.testing.assert_allclose(got["record"]["source"], np.broadcast_to(starts, (2, 3, 3)), atol=1e-6)
        np.testing.assert_allclose(got["record"]["raw_coordinates"]["target"], self.target)
        np.testing.assert_allclose(got["record"]["raw_coordinates"]["source"], source[:, :, 1])
        self.assertEqual(got["runtime"]["source"]["rng_before_sha256"], "before")

    def test_rng_state_mismatch_rejected(self):
        values = [
            (np.ones((2, 3, 14, 3), dtype=np.float32), "before", "after"),
            (np.ones((2, 3, 14, 3), dtype=np.float32), "different", "after"),
        ]
        with patch("senba_sprint.inference._torch_and_upstream", return_value=(_FakeTorch(), None, None, None, object(), None)), \
             patch("senba_sprint.inference._load_model", return_value=(object(), "a" * 64)), \
             patch("senba_sprint.inference.build_batch", return_value={}), \
             patch("senba_sprint.inference._generate", side_effect=values), \
             patch("senba_sprint.inference.Path.is_file", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "paired RNG"):
                run_pair(self.start, self.target, "AAA", Path("source.ckpt"), Path("candidate.ckpt"),
                         "a" * 64, "a" * 64, samples=2, ids=self.ids)


if __name__ == "__main__":
    unittest.main()
