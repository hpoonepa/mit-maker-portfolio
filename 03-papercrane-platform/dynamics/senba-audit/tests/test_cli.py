# Check cli contracts using local fixtures.
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from senba_sprint.__main__ import demo_records, main, read_records


class CliTests(unittest.TestCase):
    def test_demo_is_labeled_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["demo", "--output", str(output), "--bootstrap", "40"])
            self.assertEqual(code, 0)
            result = json.loads(output.read_text())
            self.assertEqual(result["evidence_status"], "SYNTHETIC_TEST_ONLY_NOT_MODEL_RESULTS")
            original = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["demo", "--output", str(output), "--bootstrap", "40"])
            self.assertEqual(code, 2)
            self.assertEqual(output.read_bytes(), original)

    def test_input_error_has_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text('{}\nnot json\n')
            with self.assertRaisesRegex(ValueError, "line 2"):
                read_records(path)

    def test_analyze_records_input_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text('\n'.join(json.dumps(record) for record in demo_records()))
            output = Path(directory) / "analysis.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["analyze", str(path), "--output", str(output), "--bootstrap", "40"])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text())
            self.assertEqual(len(report["input_receipt"]["sha256"]), 64)
            self.assertIn("NOT_INDEPENDENTLY_VERIFIED", report["evidence_status"])


if __name__ == "__main__":
    unittest.main()
