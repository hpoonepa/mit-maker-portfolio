# PDBFixer

Papercrane beta adapter for OpenMM PDBFixer 1.12, inspired by the lightweight structure utilities exposed by NeuroSnap. It repairs common structure problems—missing residues or atoms, nonstandard residues, heterogens, and hydrogens—and writes a normalized mmCIF artifact.

The default keeps heterogens and water, fills missing residues and atoms, replaces nonstandard residues, and adds hydrogens at pH 7. All operations are configurable. This is a deterministic CPU utility, so multiple seeds intentionally produce equivalent structures with distinct Papercrane artifact keys.

PDBFixer is MIT-licensed.
