"""Preserve upstream score names and distinguish PDE from PAE."""
import ast
from pathlib import Path
import unittest


class MetricsTest(unittest.TestCase):
    def test_native_scores_have_no_fabricated_missing_values(self):
        source = Path(__file__).resolve().parents[1] / "modal_app.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_numeric_metrics")
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        result = namespace["_numeric_metrics"]({"complex_plddt": 0.8, "complex_pde": 1.2, "ptm": 0, "chains": {"A": 0.9}, "unknown": float("nan"), "flag": True})
        self.assertEqual(result, {"complex_plddt": 0.8, "complex_pde": 1.2, "ptm": 0})
        predict = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_predict_impl")
        # The actual prediction path uses this extraction, without default-zero aliases.
        assignments = [n for n in ast.walk(predict) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "confidence" for t in n.targets)]
        self.assertTrue(any(isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "_numeric_metrics" for n in assignments))

    def test_dispatch_reports_actual_input_chain_count(self):
        source = Path(__file__).resolve().parents[1] / "modal_app.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "papercrane_dispatch")
        function.decorator_list = []
        for binder, expected in [(None, 1), ("ACDE", 2)]:
            namespace = {
                "TIMEOUT_MIN": 1,
                "_json_arg": lambda value, fallback: value if value is not None else fallback,
                "_resolve_cofold": lambda *args: ("MQIF", binder),
                "_binder_sequence_from_prev": lambda *args: None,
                "_predict_impl": lambda **kwargs: {"cif_bytes": b"data_test", "structure_path": "test.cif", "confidence": {"iptm": 0}},
                "_numeric_metrics": lambda values: values,
                "_upload_structure": lambda *args: "artifact.cif",
                "_emit_event": lambda event: None,
            }
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            result = namespace["papercrane_dispatch"]("job", [205], {})
            self.assertEqual(result["events"][0]["metrics"]["chain_count"], expected)
            self.assertEqual(result["events"][0]["metrics"]["iptm"], 0)


if __name__ == "__main__":
    unittest.main()
