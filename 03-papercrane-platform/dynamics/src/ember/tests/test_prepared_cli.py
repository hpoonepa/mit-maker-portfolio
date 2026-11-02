# Check prepared cli contracts using local fixtures.
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from ember.__main__ import main
from ember.candidates import group_observations
from ember.execution import ComputeDisabled, ExecutionPolicy
from ember.features import ENSEMBLE_NAMES, STATIC_NAMES
from ember.io import atomic_write_json, read_json
from ember.prepared import PreparedTarget, read_prepared, write_prepared
from ember.tests.test_contracts import HASH, observation, target
from ember.train import TrainingConfig, TrainingExample, fit, training_signature


def bundle():
    site = group_observations([replace(observation("apo1", (0, 1)), source="apo", frame_id="apo")])[0]
    return PreparedTarget(
        target(),
        (site,),
        np.zeros((1, len(STATIC_NAMES)), dtype=np.float32),
        np.zeros((1, len(ENSEMBLE_NAMES)), dtype=np.float32),
        (),
        0,
        HASH,
        {
            "checkpoint_sha256": HASH,
            "trained_group_ids": ["other"],
            "selection_group_ids": [],
            "prediction_target_id": "t1",
            "role": "full_train_inference",
        },
        "apo_only",
    )


class PreparedTests(unittest.TestCase):
    def test_roundtrip_and_feature_integrity(self):
        b = bundle()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "target"
            write_prepared(root, b)
            loaded = read_prepared(root)
            self.assertEqual(loaded.target, b.target)
            self.assertEqual(loaded.sites, b.sites)
            np.testing.assert_equal(loaded.static, b.static)
            with self.assertRaises(FileExistsError):
                write_prepared(root, b)
            meta = read_json(root / "manifest.json")
            meta["reference_path"] = "/hidden/test.json"
            atomic_write_json(root / "manifest.json", meta)
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                read_prepared(root)

    def test_candidate_frame_identity_enforced(self):
        b = bundle()
        site = group_observations([observation("f", (0, 1), frame="undeclared")])[0]
        with self.assertRaisesRegex(ValueError, "Unaccepted"):
            replace(b, sites=(site,), proposal_source="apo_and_ensemble")


class CliTests(unittest.TestCase):
    def test_default_train_and_predict_refused_before_loading_data(self):
        arguments = [
            ["predict", "--bundle", "missing", "--release", "missing"],
            [
                "train-residue",
                "--targets",
                "missing",
                "--references",
                "missing",
                "--config",
                "missing",
                "--output-dir",
                "must-not-exist",
                "--method-id",
                "x",
                "--embedding-keys",
                "missing",
                "--embedding-cache",
                "missing",
            ],
        ]
        for args in arguments:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(args)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["error"], "ComputeDisabled")

    def test_plan_is_explicitly_unexecuted(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["plan"]), 0)
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["spend_authorized"])
        self.assertFalse(plan["model_execution_authorized"])
        self.assertTrue(all(not v for v in plan["readiness"].values()))


class TrainingContractTests(unittest.TestCase):
    def test_training_gate_and_signature_change_without_model_execution(self):
        with self.assertRaises(ComputeDisabled):
            fit(
                [],
                [],
                config=TrainingConfig(),
                output_dir="unused",
                policy=ExecutionPolicy(),
                split_sha256=HASH,
                code_sha256=HASH,
            )
        example = TrainingExample(
            "t",
            "g",
            "train",
            np.zeros((2, 3), dtype=np.float32),
            np.array([0, 1], dtype=np.float32),
            np.ones(2, dtype=bool),
        )
        example.validate(TrainingConfig())
        before = training_signature([example])
        after = training_signature([replace(example, features=example.features + 1)])
        self.assertNotEqual(before, after)
        with self.assertRaisesRegex(ValueError, "refuses test"):
            replace(example, partition="test").validate(TrainingConfig())


if __name__ == "__main__":
    unittest.main()
