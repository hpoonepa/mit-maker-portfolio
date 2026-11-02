"""Remote results must carry events; detached Modal stdout is not a transport."""
import ast
from pathlib import Path
import unittest


class ModalEventContractTest(unittest.TestCase):
    def test_dispatch_returns_seed_and_done_events(self):
        source = Path(__file__).resolve().parents[1] / "modal_app.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "papercrane_dispatch")
        function.decorator_list = []
        printed = []
        namespace = {
            "DEFAULT_MODEL_SIZE": "8M",
            "_json_arg": lambda value, default: value if value is not None else default,
            "_resolve_sequences": lambda *args: [{"id": "test", "sequence": "M"}],
            "_predict_impl": lambda **kwargs: {
                "model": "test", "model_size": "8M",
                "results": [{"id": "test", "sequence": "M", "metrics": {"pll_mean": -1.0}}],
            },
            "_numeric_metrics": lambda metrics: metrics,
            "_emit_event": printed.append,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        result = namespace["papercrane_dispatch"]("job", [42], {})
        self.assertEqual(result["events"], printed)
        self.assertEqual([e["type"] for e in result["events"]], ["seed", "done"])
        self.assertEqual(result["events"][0]["seed"], 42)
        self.assertEqual(result["events"][0]["sequence"], "M")


if __name__ == "__main__":
    unittest.main()
