"""Synthetic cached-evidence integration; no learned model runs or accuracy claim."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from ember.baselines.native import fpocket_apo_prediction
from ember.evaluate import evaluate_method
from ember.export import prediction_document
from ember.features import ENSEMBLE_NAMES, ensemble_ablation
from ember.io import content_hash
from ember.mapping import AtomRecord, ChainMapping, MappedResidue
from ember.pipeline import prepare_target
from ember.prepared import read_prepared, write_prepared
from ember.schema import Observation, Reference, ReferenceSite, ResidueID
from ember.tests.test_contracts import HASH, target


class PipelineIntegrationTests(unittest.TestCase):
    def test_mapping_evidence_bundle_prediction_export_and_evaluation(self):
        item = replace(target(), sequence="ACDEFG", chain_id="AAA")
        mapping = ChainMapping(
            item.sequence,
            0,
            "AAA",
            tuple(
                MappedResidue(
                    i,
                    ResidueID("AAA", 10 + i, "A" if i == 1 else ""),
                    item.sequence[i],
                    (AtomRecord("CA", "C", (i * 3.8, 0.0, 0.0), 1.0, ""),),
                )
                for i in (0, 1, 3, 4, 5)
            ),
            "synthetic_explicit_map",
        )
        observations = [
            Observation("apo-site", "apo", "apo", (0, 1, 3), (0.0, 0.0, 0.0), 2.0),
            Observation("ensemble-site", "f0", "ensemble", (0, 1, 2, 3), (0.0, 0.0, 0.0), 3.0),
        ]
        lineage = {
            "checkpoint_sha256": HASH,
            "trained_group_ids": ["other"],
            "selection_group_ids": ["development"],
            "prediction_target_id": item.target_id,
            "role": "full_train_inference",
        }
        bundle, audit = prepare_target(
            item,
            mapping,
            np.zeros(6, dtype=np.float32),
            observations,
            valid_frame_ids=("f0",),
            requested_frames=2,
            r0_lineage=lineage,
            feature_policy_sha256=HASH,
            frame_mappings={"f0": mapping},
        )
        self.assertEqual(audit["groups_after_cap"], 1)
        self.assertEqual(bundle.ensemble[0, ENSEMBLE_NAMES.index("support_fraction")], 1.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle"
            write_prepared(path, bundle)
            recovered = read_prepared(path)
            np.testing.assert_equal(recovered.static, bundle.static)
        native = fpocket_apo_prediction(item, observations[:1], method_sha256=HASH)
        report = prediction_document(item, mapping, native)
        self.assertEqual(report["sites"][0]["residue_identifiers"][1]["apo_author_id"]["insertion_code"], "A")
        reference = Reference(item.target_id, (ReferenceSite("known", (0, 1, 3)),), HASH)
        result = evaluate_method([item], [reference], [native], native.method_id)
        self.assertEqual(result["macro_recall"]["3"], 1.0)
        before = content_hash(native)
        changed = replace(reference, sites=(ReferenceSite("other", (4, 5)),))
        result = evaluate_method([item], [changed], [native], native.method_id)
        self.assertEqual(result["macro_recall"]["3"], 0.0)
        self.assertEqual(before, content_hash(native))

    def test_count_ablation_preserves_other_features_and_width(self):
        values = np.ones((2, 2 * len(ENSEMBLE_NAMES)), dtype=np.float32)
        result = ensemble_ablation(values, "no_support_counts")
        self.assertEqual(result.shape, values.shape)
        self.assertTrue((values == 1).all())
        for index in (0, 1, 2, 25, 26, 27):
            self.assertTrue((result[:, index] == 0).all())
        self.assertTrue((result[:, 3:25] == 1).all())


if __name__ == "__main__":
    unittest.main()
