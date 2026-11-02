# RoseTTAFold3

Papercrane adapter for the open-source RF3 structure predictor in RosettaCommons Foundry 0.1.9.

- Upstream: <https://github.com/RosettaCommons/foundry/tree/production/models/rf3>
- License: BSD-3-Clause
- Input: one or more protein sequences, plus an optional ligand CCD code or SMILES
- Output: the highest-ranked all-atom mmCIF and scalar confidence metrics

RF3 does not compute MSAs on demand. This adapter intentionally supports the useful no-MSA path and sets the early-stopping threshold to zero by default so a successful run produces a structure. It remains beta until the checkpoint-backed Modal image passes a live artifact-upload smoke test.

Run the remote smoke test with `modal run tools/rf3/modal_app.py`.
