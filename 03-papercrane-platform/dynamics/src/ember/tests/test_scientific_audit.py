# Check scientific audit contracts using local fixtures.
import itertools
import random
import unittest
from dataclasses import replace
from pathlib import Path

from ember.candidates import jaccard
from ember.evaluate import evaluate_method, maximum_matching
from ember.plan import experiment_plan, preflight
from ember.report import markdown_report
from ember.schema import RankedSite
from ember.splits import validate_oof_lineage
from ember.tests.test_contracts import HASH, prediction, reference, target


class MatchingAuditTests(unittest.TestCase):
    def test_maximum_matching_agrees_with_bruteforce_on_small_graphs(self):
        rng = random.Random(15)
        for _ in range(100):
            predicted = [tuple(i for i in range(6) if rng.random() > 0.5) for _ in range(4)]
            references = [tuple(i for i in range(6) if rng.random() > 0.5) for _ in range(3)]
            best = 0
            for choices in itertools.product(range(-1, len(references)), repeat=len(predicted)):
                used = [j for j in choices if j >= 0]
                if len(used) != len(set(used)):
                    continue
                if all(j < 0 or jaccard(predicted[i], references[j]) >= 0.25 for i, j in enumerate(choices)):
                    best = max(best, len(used))
            self.assertEqual(len(maximum_matching(predicted, references, 0.25)), best)

    def test_oversized_prediction_is_penalized_and_failures_are_misses(self):
        t = target()
        p = prediction(t, [RankedSite("entire-protein", tuple(range(len(t.sequence))), 1.0, "apo")], "ok")
        result = evaluate_method([t], [reference()], [p], "method")
        self.assertEqual(result["macro_recall"]["3"], 0.0)
        failed = replace(prediction(t), status="failed", failure_reason="mapping crashed")
        result = evaluate_method([t], [reference()], [failed], "method")
        self.assertEqual(result["n_eligible_positive_targets"], 1)
        self.assertEqual(result["macro_recall"]["3"], 0.0)

    def test_report_will_not_mix_different_cohorts(self):
        a = evaluate_method([target()], [reference()], [], "baseline")
        b = evaluate_method([target("t2")], [reference("t2")], [], "other")
        with self.assertRaisesRegex(ValueError, "different cohorts"):
            markdown_report([a, b], baseline_id="baseline")
        report = markdown_report([a], baseline_id="baseline", planned_methods=["Lacuna"])
        self.assertIn("Not run", report)
        self.assertIn("incomplete", report)


class LeakageAuditTests(unittest.TestCase):
    def test_oof_early_stopping_on_scored_group_is_also_leakage(self):
        t = target("a", "g1", "train")
        lineage = {
            "checkpoint_sha256": HASH,
            "trained_group_ids": ["g2"],
            "selection_group_ids": ["g1"],
            "prediction_target_id": "a",
            "role": "out_of_fold",
        }
        with self.assertRaisesRegex(ValueError, "model selection"):
            validate_oof_lineage(t, lineage, {"g1", "g2"})

    def test_readiness_flags_alone_cannot_make_paid_preflight_pass(self):
        plan = experiment_plan()
        plan["readiness"] = {key: True for key in plan["readiness"]}
        plan["spend_authorized"] = plan["model_execution_authorized"] = True
        result = preflight(plan)
        self.assertFalse(result["ready_for_full_paid_experiment"])
        self.assertTrue(all("evidence" in message for message in result["unresolved"]))


try:
    import Bio
except ImportError:
    Bio = None


@unittest.skipIf(Bio is None, "Biopython not installed")
class RealStructureMappingTests(unittest.TestCase):
    def test_multicharacter_author_chain_and_missing_residues_from_metadata(self):
        from ember.mapping import mmcif_canonical_mapping

        root = Path(__file__).parents[1] / "research/structure-fixtures"
        mapping = mmcif_canonical_mapping(root / "7r00.cif", model_index=0, chain_id="AAA")
        self.assertEqual(len(mapping.sequence), 130)
        self.assertTrue(all(r.author_id.chain == "AAA" for r in mapping.residues))
        mapping = mmcif_canonical_mapping(root / "4os8.cif", model_index=0, chain_id="B")
        self.assertEqual(len(mapping.sequence), 190)
        self.assertEqual(sum(mapping.observed_mask), 162)
        self.assertEqual(len(mapping.author_to_canonical), 162)


if __name__ == "__main__":
    unittest.main()
