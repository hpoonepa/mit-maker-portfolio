# ESM-IF1

Fixed-backbone inverse folding with Meta's open-source ESM-IF1 model.

- Upstream: <https://github.com/facebookresearch/esm/tree/main/examples/inverse_folding>
- License: MIT
- Input: PDB/mmCIF backbone and a target chain
- Output: sampled sequence, conditional log likelihoods, and the input backbone as mmCIF

The adapter pins `fair-esm==2.0.0`. It remains beta until its legacy PyTorch Geometric stack, checkpoint download, and R2 upload pass a live Modal smoke test.
