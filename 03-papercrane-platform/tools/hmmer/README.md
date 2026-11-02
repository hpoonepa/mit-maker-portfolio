# HMMER phmmer

Protein-sequence homology scoring with HMMER's `phmmer` program.

- Upstream: <https://github.com/EddyRivasLab/hmmer>
- Release: <https://github.com/EddyRivasLab/hmmer/releases/tag/hmmer-3.4>
- User guide: <https://eddylab.org/software/hmmer/Userguide.pdf>
- License: BSD-3-Clause
- Input: one query protein sequence and one or more request-provided reference sequences
- Output: significant-hit counts, full-sequence and best-domain scores, and a sequence-bearing mmCIF artifact with the retained hit table

This integration invokes `phmmer`; it does not download or silently query a public sequence database. Because HMMER does not predict coordinates, its valid mmCIF artifact records the query polymer and analysis data without inventing a 3D model. It remains beta until the pinned source build and artifact path pass a live Modal smoke test.
