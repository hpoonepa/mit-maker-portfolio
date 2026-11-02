# DIAMOND

Fast protein homology search with BLAST-compatible tabular scoring.

- Upstream: <https://github.com/bbuchfink/diamond>
- Release: <https://github.com/bbuchfink/diamond/releases/tag/v2.2.4>
- License: GPL-3.0-only
- Input: one query protein and one or more request-provided reference sequences
- Output: hit count, top identity, coverage, E-value, bit score, and a coordinate-free sequence mmCIF with retained hits

The integration builds a temporary DIAMOND database solely from references in the request; it does not fetch or silently search a global database. It pins the official Linux release asset and remains beta until live binary and artifact smoke testing.
