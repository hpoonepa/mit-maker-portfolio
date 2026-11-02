"""Exercise the CLI boundary without importing Modal or allocating a GPU."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch


class ModalCliContractTest(unittest.TestCase):
    def test_each_backbone_is_passed_as_a_file_for_each_seed(self):
        source = Path(__file__).resolve().parents[1] / "modal_app.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_predict_impl")
        namespace = {
            "Path": Path,
            "_resolve_backbone_bytes": lambda b: (b, b"ATOM fixture"),
            "_build_fixed_positions_jsonl": lambda *args: None,
            "_parse_mpnn_fasta": lambda text, source_pdb: [{"sequence": text}],
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        calls = []

        def run(cmd, check):
            pdb = Path(cmd[cmd.index("--pdb_path") + 1])
            self.assertTrue(pdb.is_file(), "ProteinMPNN accepts one PDB file, not a directory")
            seed = int(cmd[cmd.index("--seed") + 1])
            calls.append((pdb.name, seed))
            out = Path(cmd[cmd.index("--out_folder") + 1]) / "seqs"
            out.mkdir(exist_ok=True)
            (out / f"{pdb.stem}.fa").write_text("MAAAA")

        with patch("subprocess.run", side_effect=run):
            result = namespace["_predict_impl"](["a.pdb", "b.pdb"], [1, 2])
        self.assertEqual(calls, [("a.pdb", 1), ("b.pdb", 1), ("a.pdb", 2), ("b.pdb", 2)])
        self.assertEqual(len(result["results"]), 4)


if __name__ == "__main__":
    unittest.main()
