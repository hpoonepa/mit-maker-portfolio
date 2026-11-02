# HH-suite

Sensitive profile-to-profile protein comparison with HHmake and HHalign.

- Upstream: <https://github.com/soedinglab/hh-suite>
- Release: <https://github.com/soedinglab/hh-suite/releases/tag/v3.3.0>
- License: GPL-3.0-only
- Input: query/reference sequences, two convenience `sequences` records, or explicit query/reference A3M alignments
- Output: HHalign probability, E-value, score, aligned columns, identities, similarity, sum probabilities, and a coordinate-free query mmCIF

Single sequences are accepted by turning each into a one-member A3M; explicit alignments provide the evolutionary depth that makes profile comparison most useful. No external database is queried. The official AVX2 binary remains beta-gated pending a live Modal smoke test.
