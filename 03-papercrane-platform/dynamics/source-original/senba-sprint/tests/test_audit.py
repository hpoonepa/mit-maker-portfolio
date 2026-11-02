import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from senba_sprint import audit


FIELDS = (
    "best_of_k_rmsd_improvement_vs_source_angstrom",
    "direction_cosine_improvement_vs_source",
    "displacement_magnitude_mae_improvement_vs_source_angstrom",
    audit.PERSISTENCE,
    audit.CENTROID,
    audit.SINGLE_SAMPLE,
)


def fixture():
    rows = []
    for index in range(28):
        base = (index - 1) / 100.0
        rows.append({
            "domain_id": f"domain-{index:02d}",
            **{field: base + offset / 1000.0 for offset, field in enumerate(FIELDS)},
        })
    rows[0][audit.CENTROID] = -0.01
    rows[0][audit.SINGLE_SAMPLE] = 0.001
    rows[0][audit.PERSISTENCE] = -0.02
    values = {field: np.array([row[field] for row in rows]) for field in FIELDS}
    comparison = {
        "proteins": 28,
        "bootstrap_seed": audit.BOOTSTRAP_SEED,
        "bootstrap_resamples": audit.BOOTSTRAP_RESAMPLES,
        "bootstrap_unit": "protein",
        "per_protein": rows,
        **{field: float(array.mean()) for field, array in values.items()},
        audit.SUMMARY_ALIAS: float(values[audit.CENTROID].mean()),
        "fraction_proteins_better_than_source": 27 / 28,
        "fraction_proteins_better_than_persistence": 27 / 28,
    }
    rng = np.random.default_rng(audit.BOOTSTRAP_SEED)
    indices = rng.integers(0, 28, size=(audit.BOOTSTRAP_RESAMPLES, 28))
    comparison[audit.SOURCE_CI] = np.quantile(
        values[audit.CENTROID][indices].mean(axis=1), [0.025, 0.975]
    ).tolist()
    comparison[audit.PERSISTENCE_CI] = np.quantile(
        values[audit.PERSISTENCE][indices].mean(axis=1), [0.025, 0.975]
    ).tolist()
    return {"comparison": comparison}


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = fixture()
        cls.report = audit.audit_receipt(cls.receipt)

    def test_recomputes_all_macro_means_and_published_checks(self):
        self.assertEqual(set(self.report["recomputed_protein_macro_means"]), set(FIELDS))
        self.assertTrue(self.report["all_published_arithmetic_matched"])
        self.assertTrue(all(
            check["matched"] for check in self.report["scalar_checks"].values()
        ))

    def test_win_counts_cover_centroid_single_sample_and_persistence(self):
        self.assertEqual(self.report["wins"]["centroid_vs_source"]["wins"], 27)
        self.assertEqual(self.report["wins"]["single_sample_vs_source"]["wins"], 28)
        self.assertEqual(self.report["wins"]["centroid_vs_persistence"]["wins"], 27)

    def test_bootstrap_matches_fixture_and_is_labeled(self):
        checks = self.report["bootstrap"]["ci_checks"]
        self.assertTrue(checks[audit.SOURCE_CI]["matched"])
        self.assertTrue(checks[audit.PERSISTENCE_CI]["matched"])
        self.assertIn("numpy.default_rng", self.report["bootstrap"]["algorithm"])

    def test_leave_one_out_has_every_protein_and_field(self):
        rows = self.report["leave_one_protein_out"]
        self.assertEqual(len(rows), 28)
        self.assertEqual(set(rows[0]["means"]), set(FIELDS))

    def test_summary_mismatch_is_preserved_not_hidden(self):
        receipt = fixture()
        receipt["comparison"][audit.CENTROID] += 1e-5
        report = audit.audit_receipt(receipt)
        self.assertFalse(report["scalar_checks"][audit.CENTROID]["matched"])
        self.assertFalse(report["all_published_arithmetic_matched"])

    def test_rejects_duplicate_missing_and_nonfinite_rows(self):
        cases = []
        duplicate = fixture()
        duplicate["comparison"]["per_protein"][1]["domain_id"] = "domain-00"
        cases.append(duplicate)
        missing = fixture()
        del missing["comparison"]["per_protein"][1][FIELDS[0]]
        cases.append(missing)
        nonfinite = fixture()
        nonfinite["comparison"]["per_protein"][1][FIELDS[0]] = math.nan
        cases.append(nonfinite)
        for receipt in cases:
            with self.subTest(), self.assertRaises(ValueError):
                audit.audit_receipt(receipt)

    def test_release_reader_records_hash_and_cli_output_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / audit.RECEIPT_PATH
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(fixture()))
            report = audit.audit_release(root)
            self.assertEqual(len(report["input_receipt"]["sha256"]), 64)
            output = root / "audit.json"
            self.assertEqual(audit.main(["--release-dir", str(root), "--output", str(output)]), 0)
            with self.assertRaises(SystemExit):
                audit.main(["--release-dir", str(root), "--output", str(output)])

    def test_audit_scope_and_required_inputs(self):
        self.assertIn("published-summary arithmetic checks", self.report["scope"])
        self.assertTrue(any("energy score requires raw coordinate arrays" in note for note in self.report["limitations"]))
        self.assertTrue(any("ambiguous" in note for note in self.report["limitations"]))


if __name__ == "__main__":
    unittest.main()
