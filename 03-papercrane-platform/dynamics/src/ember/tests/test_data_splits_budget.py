# Check data splits budget contracts using local fixtures.
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ember.budget import BudgetLedger, project_cost
from ember.data import build_cryptobench_reference
from ember.mapping import ChainMapping, MappedResidue
from ember.sampling import plan_bioemu
from ember.schema import ResidueID
from ember.splits import (
    SimilarityEdge,
    crossfit_folds,
    crossfit_plan,
    metadata_subset,
    partition_conflicts,
    relatedness_groups,
    validate_oof_lineage,
)
from ember.tests.test_contracts import HASH, target


class SplitTests(unittest.TestCase):
    def test_transitive_relatedness_and_overlap_audit(self):
        edges = [SimilarityEdge("a", "b", 0.5, 0.9, "fixture"), SimilarityEdge("b", "c", 0.4, 0.8, "fixture")]
        groups = relatedness_groups(["a", "b", "c", "d"], edges)
        self.assertEqual(groups["a"], groups["c"])
        self.assertNotEqual(groups["a"], groups["d"])
        items = [target("a", groups["a"], "train"), target("c", groups["c"], "test")]
        audit = partition_conflicts(items)
        self.assertFalse(audit["passed"])
        self.assertEqual(audit["group_conflicts"][0]["training_relatives_to_purge"], ["a"])

    def test_crossfit_and_subset_do_not_split_families(self):
        items = [
            target("a", "g1", "train"),
            target("b", "g1", "train"),
            target("c", "g2", "train"),
            target("d", "g3", "train"),
        ]
        folds = crossfit_folds(items)
        self.assertEqual(folds["a"], folds["b"])
        self.assertEqual(set(folds.values()), {0, 1, 2})
        self.assertEqual(folds, crossfit_folds(items[::-1]))
        plan = crossfit_plan(items)
        self.assertEqual(plan, crossfit_plan(items[::-1]))
        for run in plan["runs"]:
            a, b, c = (set(run[name + "_groups"]) for name in ("training", "selection", "prediction"))
            self.assertFalse(a & b or a & c or b & c)
            self.assertTrue(a and b and c)
            self.assertEqual(a | b | c, {"g1", "g2", "g3"})
        subset = metadata_subset(items, 1)
        self.assertEqual(len({t.group_id for t in subset}), 1)
        with self.assertRaisesRegex(ValueError, "training targets"):
            crossfit_folds([target()])

    def test_oof_lineage_rejects_training_on_self(self):
        t = target("a", "g1", "train")
        lineage = {
            "checkpoint_sha256": HASH,
            "trained_group_ids": ["g2"],
            "selection_group_ids": ["g3"],
            "prediction_target_id": "a",
            "role": "out_of_fold",
        }
        validate_oof_lineage(t, lineage, {"g1", "g2", "g3"})
        lineage["trained_group_ids"].append("g1")
        with self.assertRaisesRegex(ValueError, "seen during"):
            validate_oof_lineage(t, lineage, {"g1", "g2", "g3"})


class ReferenceTests(unittest.TestCase):
    def test_repeated_ligands_are_not_independent_reference_sites(self):
        t = replace(target(), sequence="ACD")
        mapping = ChainMapping(
            "ACD",
            0,
            "A",
            tuple(MappedResidue(i, ResidueID("A", i + 1), aa, ()) for i, aa in enumerate("ACD")),
            "fixture",
        )
        base = {
            "holo_pdb_id": "1abc",
            "holo_chain": "A",
            "ligand": "LIG",
            "ligand_index": "100",
            "ligand_chain": "A",
            "apo_pocket_selection": ["A_1", "A_2"],
        }
        ref, audit = build_cryptobench_reference(
            t, [base, dict(base, ligand_index="101")], mapping, source_sha256=HASH
        )
        self.assertEqual(len(ref.sites), 1)
        self.assertEqual(audit["unique_pair_records"], 2)
        self.assertEqual(ref.residue_labels, (1, 1, 0))
        with self.assertRaisesRegex(ValueError, "multi-chain"):
            build_cryptobench_reference(
                t, [dict(base, apo_pocket_selection=["A_1", "B_2"])], mapping, source_sha256=HASH
            )


class BudgetTests(unittest.TestCase):
    def test_reservation_idempotency_and_evaluation_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = BudgetLedger(Path(folder) / "budget.json")
            state = ledger.initialize()
            self.assertFalse(state["spend_authorized"])
            ledger.reserve("job1", "training_development", "45", input_sha256=HASH)
            ledger.reserve("job1", "training_development", "45", input_sha256=HASH)
            with self.assertRaisesRegex(ValueError, "allocation"):
                ledger.reserve("job2", "training_development", "6", input_sha256=HASH)
            job = ledger.settle("job1", "55", receipt_sha256=HASH)
            self.assertTrue(job["exceeded_reservation"])
            with self.assertRaisesRegex(ValueError, "allocation"):
                ledger.reserve("job2", "smoke", "1", input_sha256=HASH)

    def test_projection_refuses_incomplete_profiling(self):
        with self.assertRaisesRegex(ValueError, "Missing measured"):
            project_cost([], {"long": 10}, hourly_usd="1")
        result = project_cost(
            [{"stratum": "short", "total_seconds": 360, "end_to_end_measured": True}],
            {"short": 10},
            hourly_usd="2",
            fixed_usd="1",
        )
        self.assertEqual(float(result["projected_usd"]), 4.0)


class SamplingPlanTests(unittest.TestCase):
    def test_plan_does_not_launch_and_pins_real_output_interface(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "not-created"
            plan = plan_bioemu("ACD", output)
            self.assertFalse(output.exists())
            self.assertIn("--model_name", plan.sample_argv)
            self.assertIn("bioemu-v1.1", plan.sample_argv)
            self.assertIn("--outpath", plan.reconstruct_argv)
            self.assertTrue(plan.reconstructed_trajectory.endswith("samples_sidechain_rec.xtc"))
            self.assertIn("--no-md-equil", plan.reconstruct_argv)


if __name__ == "__main__":
    unittest.main()
