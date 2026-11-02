import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np

    from dynamics.ember.geometry import align_coordinates, atom_coordinates, contact_change
except ImportError:
    np = None

from dynamics.ember.mapping import (
    AtomRecord,
    ChainMapping,
    MappedResidue,
    ligand_heavy_atoms,
    map_author_sites,
    parse_author_selection,
    read_chain,
    unique_subsequence_mapping,
    write_normalized_pdb,
)
from dynamics.ember.schema import ResidueID


class MappingTests(unittest.TestCase):
    def test_missing_segments_do_not_shift_sequence_indices(self):
        self.assertEqual(unique_subsequence_mapping("ACDEFGHIK", "ACDFGHIK"), (0, 1, 2, 4, 5, 6, 7, 8))
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            unique_subsequence_mapping("AAAC", "AAC")
        with self.assertRaisesRegex(ValueError, "not an exact"):
            unique_subsequence_mapping("ACDE", "ACDF")

    def test_author_numbering_negative_and_insertion(self):
        self.assertEqual(parse_author_selection("AB_-2B"), ResidueID("AB", -2, "B"))
        mapping = ChainMapping(
            "ACD",
            0,
            "A",
            (
                MappedResidue(0, ResidueID("A", 12), "A", ()),
                MappedResidue(2, ResidueID("A", 12, "B"), "D", ()),
            ),
            "fixture",
        )
        self.assertEqual(mapping.observed_mask, (True, False, True))
        self.assertEqual(map_author_sites(["A_12B", "A_12"], mapping), (0, 2))
        with self.assertRaisesRegex(ValueError, "absent"):
            map_author_sites(["B_12"], mapping)

    def test_explicit_mapping_checks_amino_acid_identity(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            ChainMapping("AC", 0, "A", (MappedResidue(0, ResidueID("A", 1), "C", ()),), "fixture")


def pdb_atom(
    serial,
    atom,
    residue,
    chain,
    number,
    xyz,
    *,
    insertion="",
    record="ATOM",
    element="C",
    altloc="",
    occupancy=1.0,
):
    return (
        f"{record:<6}{serial:5d} {atom:^4s}{altloc:1s}{residue:>3s} {chain:1s}{number:4d}{insertion:1s}   "
        f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{occupancy:6.2f}{0.0:6.2f}          {element:>2s}"
    )


try:
    import Bio
except ImportError:
    Bio = None


@unittest.skipIf(Bio is None, "Biopython not installed")
class StructureTests(unittest.TestCase):
    def test_exact_chain_insertion_missing_residues_and_ligand_instance(self):
        lines = [
            pdb_atom(1, "CA", "ALA", "A", 10, (0, 0, 0)),
            pdb_atom(2, "CA", "ASP", "A", 10, (1, 0, 0), insertion="B"),
            pdb_atom(3, "CA", "GLY", "B", 1, (9, 0, 0)),
            pdb_atom(4, "C1", "LIG", "A", 100, (1, 2, 3), record="HETATM"),
            pdb_atom(5, "C1", "LIG", "A", 101, (100, 200, 300), record="HETATM"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.pdb"
            path.write_text("\n".join(lines) + "\nEND\n")
            mapping = read_chain(path, sequence="ACD", model_index=0, chain_id="A")
            self.assertEqual(mapping.observed_mask, (True, False, True))
            self.assertEqual(mapping.residues[1].author_id, ResidueID("A", 10, "B"))
            ligand = ligand_heavy_atoms(
                path, model_index=0, residue_id=ResidueID("A", 100), residue_name="LIG"
            )
            self.assertEqual(ligand, ((1.0, 2.0, 3.0),))
            with self.assertRaisesRegex(ValueError, "Explicit chain"):
                read_chain(path, sequence="ACD", model_index=0, chain_id="Z")
            normalized = Path(folder) / "normalized.pdb"
            lookup = write_normalized_pdb(mapping, normalized)
            self.assertEqual(lookup, {ResidueID("A", 1): 0, ResidueID("A", 3): 2})
            again = read_chain(normalized, sequence="ACD", model_index=0, chain_id="A")
            self.assertEqual(again.observed_mask, mapping.observed_mask)

    def test_alternate_locations_use_consistent_residue_alternative(self):
        lines = [
            pdb_atom(1, "CA", "ALA", "A", 1, (0, 0, 0), altloc="A", occupancy=0.6),
            pdb_atom(2, "CA", "ALA", "A", 1, (9, 9, 9), altloc="B", occupancy=0.4),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.pdb"
            path.write_text("\n".join(lines) + "\nEND\n")
            mapping = read_chain(path, sequence="A", model_index=0, chain_id="A")
            self.assertEqual(mapping.residues[0].atoms[0].coord, (0.0, 0.0, 0.0))


@unittest.skipIf(np is None, "NumPy not installed")
class GeometryTests(unittest.TestCase):
    def test_alignment_recovers_rotation_translation_without_reflection(self):
        coords = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]])
        angle = 0.7
        rot = np.array(
            [
                [math.cos(angle), -math.sin(angle), 0.0],
                [math.sin(angle), math.cos(angle), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        moved = coords @ rot + [8.0, -4.0, 12.0]
        transform = align_coordinates(moved, coords)
        np.testing.assert_allclose(transform.apply(moved), coords, atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(transform.rotation), 1.0)
        mirrored = coords * [-1, 1, 1]
        self.assertGreater(align_coordinates(mirrored, coords).rmsd, 0.1)

    def test_collinear_alignment_rejected(self):
        line = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        with self.assertRaisesRegex(ValueError, "collinear"):
            align_coordinates(line, line)

    def test_missing_coordinates_masked_and_contact_invariance(self):
        mapping = ChainMapping(
            "ACD",
            0,
            "A",
            (
                MappedResidue(0, ResidueID("A", 1), "A", (AtomRecord("CA", "C", (4.0, 2.0, 1.0), 1.0, ""),)),
                MappedResidue(2, ResidueID("A", 3), "D", ()),
            ),
            "fixture",
        )
        _, mask = atom_coordinates(mapping)
        np.testing.assert_array_equal(mask, [True, False, False])
        apo = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [3.0, 1.0, 2.0]])
        mask = np.ones(4, dtype=bool)
        self.assertEqual(contact_change(apo, apo + 100, mask, mask, (0,)), 0.0)
        moved = apo.copy()
        moved[3] += 20
        self.assertEqual(contact_change(apo, moved, mask, mask, (0,)), 1.0)


if __name__ == "__main__":
    unittest.main()
