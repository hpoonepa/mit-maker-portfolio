# Check p2rank contracts using local fixtures.
import unittest
from pathlib import Path

from ember.baselines.p2rank import parse_predictions
from ember.mapping import parse_author_selection


class P2RankTests(unittest.TestCase):
    def test_real_author_output_schema_and_mapping(self):
        path = (
            Path(__file__).parents[1]
            / "research/p2rank-misc_visualization_predict_1fbl_1fbl.pdb_predictions.csv"
        )
        import csv

        with path.open() as handle:
            rows = list(csv.reader(handle))
        ids = sorted({item for row in rows[1:] if row for item in row[9].split()})
        mapping = {parse_author_selection(item): i for i, item in enumerate(ids)}
        sites = parse_predictions(path, mapping)
        self.assertEqual(len(sites), 4)
        self.assertEqual(sites[0].rank, 1)
        self.assertEqual(sites[0].score, 9.77)
        self.assertEqual(len(sites[0].residues), 18)
        with self.assertRaisesRegex(ValueError, "outside canonical"):
            parse_predictions(path, {})


if __name__ == "__main__":
    unittest.main()
