# MMseqs2

Fast protein-sequence homology search with the MMseqs2 `easy-search` workflow.

- Upstream: <https://github.com/soedinglab/MMseqs2>
- Release: <https://github.com/soedinglab/MMseqs2/releases/tag/18-8cc5c>
- License: MIT
- Input: one query protein sequence and one or more request-provided reference sequences
- Output: hit count, top identity/E-value/bit score, and a sequence-bearing mmCIF artifact with the retained hit table

This integration does not download or silently query a global sequence database. It searches only the reference sequences supplied with the request. Because MMseqs2 does not predict coordinates, its valid mmCIF artifact records the query polymer and analysis data without inventing a 3D model. It remains beta until the pinned CPU binary and artifact path pass a live Modal smoke test.
