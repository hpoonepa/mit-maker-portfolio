# Parasail

SIMD-accelerated pairwise protein alignment using global, local, or semi-global dynamic programming.

- Upstream: <https://github.com/jeffdaily/parasail-python>
- Package: <https://pypi.org/project/parasail/1.3.4/>
- License: BSD-3-Clause (Battelle BSD-style)
- Input: a query and reference protein sequence, or exactly two `sequences` records
- Output: alignment score, identity, similarity, gaps, coverage, and a coordinate-free sequence mmCIF containing the alignment

No external database or remote alignment service is used. Since alignment does not generate 3D coordinates, the valid mmCIF artifact records the query polymer and analysis fields only. This integration remains beta until the pinned CPU image and artifact path pass a live smoke test.
