# MAFFT

Multiple protein-sequence alignment with MAFFT.

- Upstream: <https://mafft.cbrc.jp/alignment/software/>
- Linux release: <https://mafft.cbrc.jp/alignment/software/linux.html>
- Manual: <https://mafft.cbrc.jp/alignment/software/manual/manual.html>
- License: BSD-3-Clause
- Input: two or more protein sequences
- Output: alignment length/conservation/gap metrics and a sequence-bearing mmCIF artifact containing the complete alignment in a custom data category

The `auto`, L-INS-i, G-INS-i, E-INS-i, and FFT-NS-2 strategies are supported. Because MAFFT does not predict coordinates, its valid mmCIF artifact records the first polymer plus the alignment without inventing a 3D model. It remains beta until the pinned official Linux package and artifact path pass a live Modal smoke test.
