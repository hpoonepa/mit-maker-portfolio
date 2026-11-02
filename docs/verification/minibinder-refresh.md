# MiniBinder checks, 31 October 2026

- 49 focused tests passed in `tests/test_tri_objective.py` and `tests/test_consensus_rank.py`.
- CLI target listing and the consensus scorer's built-in self-test passed.
- All 345 Python files retain the same executable AST as the previous portfolio snapshot, ignoring only module docstrings.
- All 22 notebook code-cell objects are unchanged. Six existing TypeScript/TSX files retain identical scanner tokens.
- Shell scripts pass syntax checks; comment edits preserve their executable bodies.
- The first-round export contains nine negative and six unknown designs; the second contains one positive among twenty designs. The reported apparent affinity is 604 nM, with replicate values of 546 and 666 nM.

These checks used available local dependencies. They do not establish that GPU design dependencies, PRINCE services, or cloud backends will run without the setup described in their own guides. No scientific campaign or assay was rerun.
