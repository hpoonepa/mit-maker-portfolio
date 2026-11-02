# ProDy

Coarse-grained protein dynamics analysis with anisotropic or Gaussian network models.

- Upstream: <https://github.com/prody/ProDy>
- Release: <https://github.com/prody/ProDy/releases/tag/v2.6.1>
- License: MIT
- Input: PDB/mmCIF protein structure and optional ProDy atom selection
- Output: mode eigenvalues, collectivity, mean-square fluctuation summaries, radius of gyration, and the analyzed structure as mmCIF

The CPU adapter operates on selected C-alpha atoms and limits requested modes to keep runs bounded. It remains beta until representative structures pass a live artifact smoke test.
