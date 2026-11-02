# ESMFold

Self-hosted Papercrane adapter for Meta's open-source ESMFold v1 model.

- Upstream: <https://github.com/facebookresearch/esm>
- License: MIT
- Input: protein sequences; `:` may separate multimer chains through direct API use
- Output: mmCIF structures and pLDDT statistics

ESMFold is a fast, MSA-free screening fold rather than a replacement for modern all-atom complex predictors. The image pins `fair-esm==2.0.0` and the OpenFold commit recommended by upstream. It remains beta until the legacy CUDA/OpenFold stack and artifact upload pass a live Modal smoke test.

Run the remote smoke test with `modal run tools/esmfold/modal_app.py`.
