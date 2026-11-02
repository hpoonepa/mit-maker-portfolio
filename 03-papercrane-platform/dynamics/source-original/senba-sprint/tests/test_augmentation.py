import copy
import unittest

from senba_sprint.augmentation import build_prefixes


BASE = 20260904


def record(index, block=0):
    seed = BASE + index + block * 1_000_000
    values = [[[float(block), float(index), 0.0]] for _ in range(4)]
    return {
        "protein_id": "p", "replica_id": str(index // 4), "start_id": str(index),
        "training_seed": "t", "inference_seed": str(seed), "units": "angstrom",
        "alignment": "start_aligned", "start": [[0., 0., 0.]], "target": [[1., 0., 0.]],
        "source": copy.deepcopy(values), "candidate": copy.deepcopy(values),
        "raw_coordinates": {"target": [[1., 0., 0.]], "source": copy.deepcopy(values), "candidate": copy.deepcopy(values)},
        "data_receipt": {"npz_sha256": "receipt"},
        "evaluator": "new_frozen_checkpoint_paired_evaluator_v1",
        "reproduction_status": "NEW_EVALUATOR_NOT_PROVEN_OLD_REPRODUCTION",
        "target_frame": index + 50,
        "provenance": {
            "upstream_repository": "repo", "upstream_revision": "rev", "source_checkpoint_sha256": "source",
            "candidate_checkpoint_sha256": "candidate", "paired_seed": seed, "samples": 4, "ode_steps": 10,
        },
    }


def inputs():
    original = [record(index) for index in range(20)]
    extra = []
    for block in (1, 2, 3):
        for index in range(20):
            row = record(index, block)
            row["block_id"] = block
            row["provenance"]["augmentation"] = {
                "block_id": block, "generation_seed": BASE + index + block * 1_000_000,
                "kind": "k4_extension_for_derived_k16",
            }
            extra.append(row)
    return original, extra


class AugmentationTests(unittest.TestCase):
    def test_generated_prefixes_preserve_each_original_draw_exactly(self):
        original, extra = inputs()
        prefixes = build_prefixes(original, extra, {"original": "hash"})
        self.assertEqual({size: len(rows) for size, rows in prefixes.items()}, {4: 20, 8: 20, 16: 20})
        blocks = [original[0], extra[0], extra[20], extra[40]]
        for size, count in ((4, 1), (8, 2), (16, 4)):
            merged = prefixes[size][0]
            for field in ("source", "candidate"):
                self.assertEqual(merged[field], sum((row[field] for row in blocks[:count]), []))
                self.assertEqual(merged["raw_coordinates"][field], sum((row["raw_coordinates"][field] for row in blocks[:count]), []))
            self.assertEqual(merged["provenance"]["augmentation"]["block_ids"], list(range(count)))

    def test_rejects_altered_target(self):
        original, extra = inputs()
        extra[0]["target"] = [[2., 0., 0.]]
        with self.assertRaisesRegex(ValueError, "altered"):
            build_prefixes(original, extra)

    def test_rejects_gauge_units_and_model_metadata_mismatches(self):
        mutations = (
            ("alignment", "other_gauge"),
            ("units", "nanometer"),
            ("target_frame", 999),
            ("provenance.ode_steps", 11),
            ("provenance.source_checkpoint_sha256", "other-checkpoint"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                original, extra = inputs()
                target = extra[0]
                if field.startswith("provenance."):
                    target["provenance"][field.split(".", 1)[1]] = value
                else:
                    target[field] = value
                with self.assertRaises(ValueError):
                    build_prefixes(original, extra)

    def test_rejects_duplicate_and_missing_blocks(self):
        original, extra = inputs()
        extra[1] = copy.deepcopy(extra[0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_prefixes(original, extra)
        original, extra = inputs()
        with self.assertRaisesRegex(ValueError, "exactly 20 original records and 60"):
            build_prefixes(original, extra[:-1])


if __name__ == "__main__":
    unittest.main()
