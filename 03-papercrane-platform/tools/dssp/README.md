# DSSP

Assigns protein secondary structure from atomic coordinates with `mkdssp` and returns residue-level summary metrics.

- Upstream: <https://github.com/PDB-REDO/dssp>
- Source tag: <https://github.com/PDB-REDO/dssp/tree/v4.6.1>
- License: BSD-2-Clause
- Input: PDB/mmCIF protein structure
- Output: helix, strand, turn, bend, loop, chain, and accessibility metrics plus DSSP's annotated mmCIF

The adapter pins the stable 4.6.1 source tag. It remains beta until the C++ source build and both mmCIF and legacy-output paths pass a live smoke test.
