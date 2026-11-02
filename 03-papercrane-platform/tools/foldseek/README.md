# Foldseek

Fast pairwise comparison of protein structures with Foldseek.

- Upstream: <https://github.com/steineggerlab/foldseek>
- License: GPL-3.0
- Input: query and partner PDB/mmCIF structures
- Output: TM-score, LDDT, sequence identity, homology probability, and the query structure as mmCIF

This adapter intentionally performs pairwise alignment without downloading a multi-hundred-gigabyte structure database. It remains beta until the pinned static binary and artifact path pass a live Modal smoke test.
