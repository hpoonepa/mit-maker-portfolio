# OpenMM Relax

All-atom structure preparation and local energy minimization with OpenMM.

- Upstream: <https://github.com/openmm/openmm>
- License: MIT/LGPL components; see upstream `Licenses.txt`
- Input: PDB/mmCIF protein structure
- Output: minimized mmCIF plus before/after potential energy

PDBFixer adds missing atoms and hydrogens before an implicit-solvent Amber minimization. The integration remains beta until representative structures pass live smoke tests.
