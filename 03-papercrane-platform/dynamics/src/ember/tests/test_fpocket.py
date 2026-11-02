# Check fpocket contracts using local fixtures.
import shutil
import tempfile
import unittest
from pathlib import Path

from ember.baselines.fpocket import PocketOutputError, parse_info, parse_output, parse_pocket
from ember.schema import ResidueID

RESEARCH = Path(__file__).parents[1] / "research"


class FpocketTests(unittest.TestCase):
    def test_real_upstream_numbering_residue_membership_and_vertex_center(self):
        prefix = "fpocket-tests_reference_output_1ATP_out_"
        info = parse_info(RESEARCH / (prefix + "1ATP_info.txt"))
        atoms = RESEARCH / (prefix + "pockets_pocket1_atm.pdb")
        authors = sorted(
            {
                ResidueID(line[21].strip(), int(line[22:26]), line[26].strip())
                for line in atoms.read_text().splitlines()
                if line.startswith("ATOM")
            },
            key=lambda r: (r.chain, r.number, r.insertion_code),
        )
        mapping = {author: i for i, author in enumerate(authors)}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "pockets").mkdir()
            shutil.copy(atoms, path / "pockets/pocket1_atm.pdb")
            shutil.copy(RESEARCH / (prefix + "pockets_pocket1_vert.pqr"), path / "pockets/pocket1_vert.pqr")
            result = parse_pocket(path, 1, info[1], frame_id="apo", source="apo", residue_mapping=mapping)
            self.assertEqual(result.volume, 590.402)
            self.assertEqual(result.detector_score, 0.977)
            self.assertEqual(len(result.residues), len(authors))
            self.assertNotEqual(len(result.residues), 106)  # spheres are not residues
            self.assertNotEqual(result.center, (0.0, 0.0, 0.0))
            (path / "pockets/pocket1_vert.pqr").unlink()
            with self.assertRaisesRegex(PocketOutputError, "Missing"):
                parse_pocket(path, 1, info[1], frame_id="apo", source="apo", residue_mapping=mapping)

    def test_missing_or_malformed_output_is_not_successful_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with self.assertRaisesRegex(PocketOutputError, "Missing"):
                parse_output(path, "input", frame_id="apo", source="apo", residue_mapping={})
            (path / "input_info.txt").write_text("broken output")
            with self.assertRaises(PocketOutputError):
                parse_output(path, "input", frame_id="apo", source="apo", residue_mapping={})
            with self.assertRaisesRegex(PocketOutputError, "contradicts"):
                parse_output(
                    path,
                    "input",
                    frame_id="apo",
                    source="apo",
                    residue_mapping={},
                    zero_pockets_confirmed=True,
                )


if __name__ == "__main__":
    unittest.main()
