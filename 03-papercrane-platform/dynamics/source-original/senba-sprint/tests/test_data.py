import unittest
from senba_sprint.data import fixed_starts, atom_mapping


class DataTests(unittest.TestCase):
    def test_frozen_frame_pairs(self):
        self.assertEqual(fixed_starts(410), [0, 119, 239, 359])
        self.assertEqual(fixed_starts(450), [0, 133, 266, 399])
        for count in [0, 50, 51, 53]:
            with self.assertRaises(ValueError):
                fixed_starts(count)

    def test_caps_are_ignored_and_required_atoms_preserved(self):
        rows = [f'ATOM  {i:5d} {name:^4s} ALA A   1       1.000   2.000   3.000'
                for i, name in enumerate(['CAY', 'N', 'CA', 'C', 'O', 'CB'], 1)]
        seq, mapping, atoms = atom_mapping('\n'.join(rows), {'ALA': ['N','CA','C','O','CB'] + ['']*9}, {'ALA':'A'})
        self.assertEqual(seq, 'A')
        self.assertEqual(mapping[0,:5].tolist(), [1,2,3,4,5])
        self.assertEqual(len(atoms), 6)


if __name__ == '__main__':
    unittest.main()
