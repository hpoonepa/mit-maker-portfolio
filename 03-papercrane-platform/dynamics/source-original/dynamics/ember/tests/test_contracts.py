import itertools
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from dynamics.ember.candidates import (
    GroupingConfig,
    best_per_frame,
    cap_candidates,
    group_observations,
    ranked_unique,
)
from dynamics.ember.evaluate import average_precision, evaluate_method, maximum_matching, paired_bootstrap
from dynamics.ember.io import atomic_write_json, content_hash, read_json
from dynamics.ember.schema import (
    Observation,
    Prediction,
    RankedSite,
    Reference,
    ReferenceSite,
    Target,
    from_dict,
    validate_targets,
)

HASH = "a" * 64


def target(name="t1", group="g1", partition="test"):
    return Target(
        name, "ACDEFGHIKLMNPQRSTVWY", "fixture", HASH, "apo.pdb", HASH, 0, "A", "1", group, partition, True
    )


def reference(name="t1", residues=(0, 1, 2)):
    return Reference(name, (ReferenceSite("r1", residues),), HASH)


def prediction(t, sites=(), status="no_candidates", method="method"):
    return Prediction(t.target_id, method, status, tuple(sites), content_hash(t), HASH)


def observation(name, residues, frame="frame1", score=1.0):
    return Observation(name, frame, "ensemble", tuple(residues), (1.0, 2.0, 3.0), score)


class SchemaTests(unittest.TestCase):
    def test_unknown_inference_reference_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            from_dict(Target, {**vars(target()), "reference_sites": [[1, 2]]})

    def test_partition_and_sequence_leakage_rejected(self):
        a = target(partition="train")
        b = replace(target("t2", "g2"), partition="test")
        with self.assertRaisesRegex(ValueError, "identical sequence"):
            validate_targets([a, b])
        with self.assertRaisesRegex(ValueError, "group crosses"):
            validate_targets([a, replace(b, group_id="g1", sequence="ACDEFG")])

    def test_status_and_frame_accounting(self):
        s = RankedSite("s1", (0, 1), 1.0, "ensemble")
        with self.assertRaisesRegex(ValueError, "requires valid"):
            prediction(target(), [s], "ok")
        with self.assertRaisesRegex(ValueError, "Unsuccessful"):
            prediction(target(), [s], "failed")
        with self.assertRaisesRegex(ValueError, "Frame counts"):
            replace(prediction(target()), requested_frames=1, valid_frames=2)

    def test_json_rejects_nonfinite_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.json"
            atomic_write_json(path, {"hello": "world"})
            with self.assertRaises(ValueError):
                atomic_write_json(path, {"x": float("nan")})
            self.assertEqual(read_json(path), {"hello": "world"})
            path.write_text('{"a": 1, "a": 2}')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_json(path)


class CandidateTests(unittest.TestCase):
    def test_no_single_link_bridge_and_permutation_invariance(self):
        # A-B and B-C overlap by 1/3; A-C do not overlap.
        obs = [observation("a", (0, 1)), observation("b", (1, 2)), observation("c", (2, 3))]
        hashes = set()
        for permutation in itertools.permutations(obs):
            sites = group_observations(list(permutation), GroupingConfig(minimum_jaccard=0.3))
            self.assertEqual(len(sites), 2)
            hashes.add(content_hash(sites))
        self.assertEqual(len(hashes), 1)

    def test_medoid_not_residue_union_and_rare_frames_retained(self):
        obs = [observation("a", (0, 1, 2)), observation("b", (1, 2, 3))]
        site = group_observations(obs)[0]
        self.assertEqual(site.residues, (0, 1, 2))
        self.assertEqual(len(best_per_frame(site)), 1)
        self.assertEqual(len(group_observations(obs[:1])), 1)

    def test_duplicate_frame_observation_does_not_inflate_support(self):
        obs = [
            observation("a", (0, 1)),
            observation("b", (0, 1), score=2.0),
            observation("c", (0, 1), frame="frame2"),
        ]
        selected = best_per_frame(group_observations(obs)[0])
        self.assertEqual([o.observation_id for o in selected], ["b", "c"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            group_observations(obs + obs[:1])

    def test_cap_and_dedup_have_stable_ties(self):
        a = RankedSite("a", (0, 1), 1.0, "apo")
        b = RankedSite("b", (0, 1, 2), 2.0, "apo")
        c = RankedSite("c", (4, 5), 1.0, "apo")
        self.assertEqual([s.site_id for s in ranked_unique([a, b, c], top_k=3)], ["b", "c"])
        self.assertEqual(ranked_unique([a], top_k=0), [])
        sites = group_observations([observation("a", (0, 1)), observation("b", (4, 5), score=2.0)])
        kept, dropped = cap_candidates(sites, 1)
        self.assertEqual(kept[0].residues, (4, 5))
        self.assertEqual(len(dropped), 1)


class EvaluationTests(unittest.TestCase):
    def test_three_output_budget_cannot_recover_four_distinct_sites(self):
        item = target()
        truth = Reference(item.target_id, tuple(ReferenceSite(f"r{i}", (i,)) for i in range(4)), HASH)
        sites = [RankedSite(f"s{i}", (i,), float(4 - i), "apo") for i in range(4)]
        result = evaluate_method([item], [truth], [prediction(item, sites, "ok")], "method")
        self.assertEqual(result["macro_recall"]["3"], 0.75)
        self.assertEqual(result["macro_output_budget_ceiling"]["3"], 0.75)
        self.assertEqual(result["macro_recall"]["5"], 1.0)

    def test_matching_reassigns_instead_of_greedy_undercount(self):
        # First prediction can hit either reference. Second can only hit R0.
        matches = maximum_matching([(0, 1, 2, 3), (0, 1)], [(0, 1), (2, 3)], 0.5)
        self.assertEqual(matches, [(0, 1), (1, 0)])
        self.assertEqual(len(maximum_matching([(0, 1)] * 3, [(0, 1)], 0.25)), 1)

    def test_missing_prediction_remains_miss_and_top_k_is_fixed(self):
        t1, t2 = target(), target("t2", "g2")
        bad = [RankedSite(f"bad{i}", (i + 5,), 10.0 - i, "apo") for i in range(3)]
        good = RankedSite("good", (0, 1, 2), 0.0, "apo")
        result = evaluate_method(
            [t1, t2], [reference(), reference("t2")], [prediction(t1, bad + [good], "ok")], "method"
        )
        self.assertEqual(result["macro_recall"]["3"], 0.0)
        self.assertEqual(result["macro_recall"]["5"], 0.5)
        self.assertEqual(result["status_counts"]["missing_prediction"], 1)
        self.assertFalse(result["cost_complete"])

    def test_missing_reference_is_protocol_error(self):
        with self.assertRaisesRegex(ValueError, "valid frozen reference"):
            evaluate_method([target()], [], [], "method")

    def test_negative_controls_do_not_receive_perfect_recall(self):
        result = evaluate_method([target()], [Reference("t1", (), HASH)], [], "method")
        self.assertIsNone(result["macro_recall"]["3"])
        self.assertEqual(result["n_negative_controls"], 1)

    def test_source_input_and_mixed_method_hash_checked(self):
        p = replace(prediction(target()), input_sha256="b" * 64)
        with self.assertRaisesRegex(ValueError, "Input hash"):
            evaluate_method([target()], [reference()], [p], "method")

    def test_average_precision_groups_ties_and_handles_masks(self):
        self.assertEqual(average_precision([1, 0], [1.0, 1.0]), 0.5)
        self.assertAlmostEqual(average_precision([1, 0, 1], [3.0, 2.0, 1.0]), 5 / 6)
        self.assertIsNone(average_precision([0, 0], [1.0, 2.0]))
        self.assertEqual(average_precision([1, 0], [0.0, 1.0], [True, False]), 1.0)

    def test_paired_bootstrap_requires_same_complete_cohort(self):
        targets = [target(), target("t2", "g2")]
        refs = [reference(), reference("t2")]
        good = [prediction(t, [RankedSite("s", (0, 1, 2), 1.0, "apo")], "ok") for t in targets]
        left = evaluate_method(targets, refs, good, "method")
        right = evaluate_method(targets, refs, [], "method")
        ci = paired_bootstrap(left, right, resamples=50)
        self.assertEqual(ci["difference"], 1.0)
        self.assertEqual(ci["ci95"], [1.0, 1.0])
        right["cohort_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "identical cohort"):
            paired_bootstrap(left, right)


if __name__ == "__main__":
    unittest.main()
