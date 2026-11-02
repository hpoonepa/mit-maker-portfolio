# PDBe Arpeggio

Rule-based classification of interatomic interactions in protein structures and complexes.

- Upstream: <https://github.com/PDBeurope/arpeggio>
- Package: <https://pypi.org/project/pdbe-arpeggio/1.4.4/>
- License: GPL-3.0-only
- Input: mmCIF/PDB structure plus optional Arpeggio atom or residue selections
- Output: total contacts, interaction-type counts, distance summaries, selected/intermolecular counts, and the analyzed structure as mmCIF

The upstream implementation operates on mmCIF, so PDB input is converted without changing coordinates. Open Babel adds hydrogens internally as required by Arpeggio. The integration remains beta until representative structures pass a live artifact smoke test.
