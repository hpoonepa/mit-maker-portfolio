# CD-HIT

Fast clustering and redundancy reduction for supplied protein sequences.

- Upstream: <https://github.com/weizhongli/cdhit>
- Release: <https://github.com/weizhongli/cdhit/releases/tag/V4.8.1>
- License: GPL-2.0-only
- Input: two or more request-provided protein sequences
- Output: cluster count, redundancy, representative coverage, largest cluster, and a coordinate-free sequence mmCIF with cluster assignments

The adapter selects CD-HIT's documented word size from the requested identity threshold and searches only the sequences in the request. It never downloads a sequence database. This integration remains beta until the pinned source build and artifact path pass a live smoke test.
