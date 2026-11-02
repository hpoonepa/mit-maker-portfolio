import copy
import unittest
from dataclasses import asdict

from dynamics.ember.io import content_hash
from dynamics.ember.release_contract import BOUND_FIELDS, release_binding, validate_release_checkpoint
from dynamics.ember.train import TrainingConfig


class ReleaseContractTests(unittest.TestCase):
    def test_preprocessing_and_training_groups_are_bound_to_checkpoint(self):
        config = asdict(TrainingConfig(kind="site_linear"))
        release = dict.fromkeys(BOUND_FIELDS)
        release.update(
            kind="site_linear",
            width=28,
            ensemble_width=None,
            dropout=0.1,
            ensemble_variant="all",
            split_sha256="a" * 64,
            code_sha256="b" * 64,
            training_groups=["train"],
            selection_groups=["dev"],
            static_normalizer={"mean": [1.0]},
        )
        signature = {
            "release_binding_sha256": release_binding(release),
            "config": content_hash(config),
            "split_sha256": "a" * 64,
            "code_sha256": "b" * 64,
        }
        release["fit_signature"] = signature
        checkpoint = {"signature": signature, "config": config, "width": 28, "ensemble_width": None}
        validate_release_checkpoint(release, checkpoint)
        for field, replacement in (
            ("training_groups", ["different"]),
            ("static_normalizer", {"mean": [10.0]}),
            ("ensemble_variant", "no_support_counts"),
            ("dropout", 0.4),
        ):
            altered = copy.deepcopy(release)
            altered[field] = replacement
            with self.assertRaises(ValueError):
                validate_release_checkpoint(altered, checkpoint)


if __name__ == "__main__":
    unittest.main()
