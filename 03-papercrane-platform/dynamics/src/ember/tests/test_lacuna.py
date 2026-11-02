# Check lacuna contracts using local fixtures.
import tempfile
import unittest
from pathlib import Path

from ember.baselines.lacuna import parse_report
from ember.io import atomic_write_json, read_json
from ember.schema import ResidueID


class LacunaParserTests(unittest.TestCase):
    def test_real_upstream_report_preserves_native_order_and_apo_accounting(self):
        path = Path(__file__).parents[1] / "research/lacuna-paper_figures_software_kras_A_pocket_report.json"
        raw = read_json(path)
        lookup = {}
        for pocket in raw["pockets"]:
            for label in pocket["lining_residues"]:
                residue, chain = label.split(":")
                number = int(residue[3:])
                lookup[ResidueID(chain, number)] = number - 1
        report = parse_report(path, lookup)
        self.assertEqual(report.n_conformers_including_apo, 21)
        self.assertEqual(len(report.sites), 6)
        self.assertEqual(report.sites[0].score, -1.0)
        self.assertEqual(report.ranked_by, "learned")
        self.assertEqual(report.sites[0].evidence, "ensemble")
        with self.assertRaisesRegex(ValueError, "outside declared"):
            parse_report(path, {})
        with tempfile.TemporaryDirectory() as folder:
            raw["pockets"][0]["appears_in_conformers"].append(21)
            modified = Path(folder) / "invalid.json"
            atomic_write_json(modified, raw)
            with self.assertRaisesRegex(ValueError, "support-frame"):
                parse_report(modified, lookup)


if __name__ == "__main__":
    unittest.main()
