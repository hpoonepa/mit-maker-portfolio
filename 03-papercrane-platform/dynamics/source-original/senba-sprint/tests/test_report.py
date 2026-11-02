import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from senba_sprint.report import build_report, main


def record(protein="p1", start_id="s1", source_shift=1.0):
    start = np.array([[0., 0., 0.], [1., 0., 0.]])
    target = start + [0., 1., 0.]
    source = np.stack([target + [source_shift, 0, 0], target + [source_shift + 1, 0, 0]])
    candidate = source - [.5, 0, 0]
    return {
        "protein_id": protein, "replica_id": "r1", "start_id": start_id,
        "training_seed": "seed1", "inference_seed": "draw1", "units": "angstrom",
        "alignment": "start_aligned", "start": start.tolist(), "target": target.tolist(),
        "source": source.tolist(), "candidate": candidate.tolist(),
        "raw_coordinates": {"target": target.tolist(), "source": source.tolist(), "candidate": candidate.tolist()},
    }


class ReportTests(unittest.TestCase):
    def write(self, root, name, rows):
        path = Path(root) / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_one_protein_is_explicitly_technical_pilot(self):
        result = build_report([record()], n_bootstrap=10)
        warnings = " ".join(result["report"]["warnings"])
        self.assertIn("TECHNICAL_PILOT_ONLY", warnings)
        self.assertIn("no scientific significance or inference", warnings)
        self.assertEqual(result["report"]["raw_coordinate_provenance"]["status"], "RAW_CA_COORDINATES_PRESENT")
        self.assertAlmostEqual(result["analysis"]["per_transition"][0]["persistence"]["persistence_ca_rmsd"], 1.0)

    def test_cli_merges_files_and_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.write(directory, "one.jsonl", [record("p1")])
            second = self.write(directory, "two.jsonl", [record("p2")])
            output = Path(directory) / "report"
            self.assertEqual(main(["--records", str(first), "--records", str(second), "--output-dir", str(output)]), 0)
            result = json.loads((output / "analysis.json").read_text())
            self.assertEqual(result["report"]["counts"]["n_proteins"], 2)
            self.assertTrue((output / "results.md").is_file())
            with self.assertRaises(SystemExit):
                main(["--records", str(first), "--output-dir", str(output)])

    def test_duplicate_and_malformed_records_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate record ID"):
            build_report([record(), record()], n_bootstrap=5)
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.jsonl"
            bad.write_text("not json\n")
            with self.assertRaises(SystemExit):
                main(["--records", str(bad), "--output-dir", str(Path(directory) / "out")])

    def test_mixed_k_is_not_concatenated(self):
        first, second = record(), record(start_id="s2")
        second["source"].append(second["source"][0])
        second["candidate"].append(second["candidate"][0])
        with self.assertRaisesRegex(ValueError, "mixed ensemble sizes"):
            build_report([first, second], n_bootstrap=5)


if __name__ == "__main__":
    unittest.main()
