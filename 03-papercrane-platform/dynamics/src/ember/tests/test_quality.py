# Check quality contracts using local fixtures.
import unittest
from dataclasses import replace

from ember.mapping import AtomRecord, ChainMapping, MappedResidue
from ember.quality import screen_structure
from ember.schema import ResidueID


def mapping():
    residues = []
    for i in range(4):
        x = i * 3.8
        atoms = tuple(
            AtomRecord(name, element, (x + dx, y, 0.0), 1.0, "")
            for name, element, dx, y in [
                ("N", "N", -1.2, 0.0),
                ("CA", "C", 0.0, 0.0),
                ("C", "C", 1.2, 0.0),
                ("O", "O", 1.4, 1.0),
                ("CB", "C", 0.0, 1.5),
            ]
        )
        residues.append(MappedResidue(i, ResidueID("A", i + 1), "A", atoms))
    return ChainMapping("AAAA", 0, "A", tuple(residues), "fixture")


class QualityTests(unittest.TestCase):
    def test_complete_sidechains_and_gross_clashes_are_separate_from_ca_quality(self):
        original = mapping()
        self.assertTrue(screen_structure(original)["accepted"])
        residue = original.residues[0]
        missing = replace(
            original, residues=(replace(residue, atoms=residue.atoms[:-1]),) + original.residues[1:]
        )
        report = screen_structure(missing)
        self.assertFalse(report["accepted"])
        self.assertTrue(report["ca"]["accepted"])
        self.assertEqual(report["incomplete_residues"][0]["missing_atoms"], ["CB"])
        moved = replace(residue.atoms[-1], coord=original.residues[-1].atoms[-1].coord)
        clash = replace(
            original,
            residues=(replace(residue, atoms=residue.atoms[:-1] + (moved,)),) + original.residues[1:],
        )
        self.assertFalse(screen_structure(clash)["accepted"])
        self.assertGreater(screen_structure(clash)["gross_nonlocal_clash_count"], 0)


if __name__ == "__main__":
    unittest.main()
