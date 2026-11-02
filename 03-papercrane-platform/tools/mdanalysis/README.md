# MDAnalysis

Computes RMSD, radius of gyration, centroid, and coordinate extents for a protein structure or multi-model structure.

- Upstream: <https://github.com/MDAnalysis/mdanalysis>
- Release: <https://github.com/MDAnalysis/mdanalysis/releases/tag/package-2.10.0>
- License: LGPL-3.0-or-later (packaged library; individual contributions are LGPL-2.1-or-later)
- Input: PDB/mmCIF target, optional PDB/mmCIF reference, and an MDAnalysis atom selection
- Output: per-ensemble summary metrics plus the analyzed target as mmCIF

The adapter pins the stable 2.10.0 release. RMSD is calculated after centering and optimal superposition against the optional reference or the target's first model. It remains beta until static, reference, and multi-model inputs pass live smoke tests.
