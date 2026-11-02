# Dynamics sources and credits

SENBA fine-tunes MarS-FM. The saved Studio examples compare model endpoints with recorded mdCATH simulation frames. The scientific models and data used by the application are credited below.

## SENBA and Studio

| Resource | Role and source |
| --- | --- |
| [SENBA pinned release](https://huggingface.co/vkali08/senba/tree/90cce9e822d511459a206ae3a06cbd8dbb243b09) | Retained local release manifest, protocols and training/selection receipts. |
| [MarS-FM paper](https://arxiv.org/abs/2509.24779) | Kapuśniak, K.; Gabellini, C.; Bronstein, M.; Tossou, P.; Di Giovanni, F. MarS-FM: Generative Modeling of Molecular Dynamics via Markov State Models. arXiv:2509.24779 (2025), v3 (2026). |
| [MarS-FM source](https://github.com/valence-labs/mars-fm/tree/4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946) | MIT; nested third-party notices apply separately. |
| [MarS-FM source checkpoint](https://huggingface.co/valencelabs/mars-fm) | Official upstream README links checkpoint repository. |
| [mdCATH data release](https://huggingface.co/datasets/compsciencelab/mdCATH/tree/5e3ed8aec62b689e01751db16275fdcdbc39e47f) | CC BY 4.0 |
| [mdCATH paper](https://doi.org/10.1038/s41597-024-04140-z) | Mirarchi, A.; Giorgino, T.; De Fabritiis, G. mdCATH: A Large-Scale MD Dataset for Data-Driven Computational Biophysics. Scientific Data 11, 1299 (2024). |
| [ESM attention source](https://github.com/facebookresearch/esm/blob/main/esm/multihead_attention.py) | MIT (Meta Platforms, Inc. and affiliates) |
| [ESM license](https://github.com/facebookresearch/esm/blob/main/LICENSE) | MIT |
| [OpenFold](https://github.com/aqlaboratory/openfold) | Apache-2.0 |
| [Three.js](https://github.com/mrdoob/three.js) | MIT; retained studio/static/vendor/THREE-LICENSE verified locally. |

## Later pocket-model experiments

Ember is implemented research code without a trained release in this snapshot. Its input sources retain their pinned revisions and licenses.

| Project | Retained revision |
| --- | --- |
| [skrhakv/CryptoBench](https://github.com/skrhakv/CryptoBench/tree/9a3432f479325ca3c9fdc3b8612715ab5b6edecc) | `9a3432f479325ca3c9fdc3b8612715ab5b6edecc` |
| [microsoft/bioemu](https://github.com/microsoft/bioemu/tree/8babb71563e97dc1feb9e3e2fbc00a1224b6a3a7) | `8babb71563e97dc1feb9e3e2fbc00a1224b6a3a7` |
| [mooreneural/lacuna](https://github.com/mooreneural/lacuna/tree/31660b7634b8d2ef473e8082eae0c117cd5aee50) | `31660b7634b8d2ef473e8082eae0c117cd5aee50` |
| [skrhakv/seq2pocket](https://github.com/skrhakv/seq2pocket/tree/add93ce0803985087347ec8d6078229a7d085184) | `add93ce0803985087347ec8d6078229a7d085184` |
| [Discngine/fpocket](https://github.com/Discngine/fpocket/tree/4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066) | `4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066` |
| [Gervasiolab/CryptoBank](https://github.com/Gervasiolab/CryptoBank/tree/9d973e6b5787016ecddc86c253aa89334588e999) | `9d973e6b5787016ecddc86c253aa89334588e999` |
| [rdk/p2rank](https://github.com/rdk/p2rank/tree/369c64e0d368b88c2b2c8a7386af77bc87af92e5) | `369c64e0d368b88c2b2c8a7386af77bc87af92e5` |

## Vendored implementation notices

MarS-FM identifies its multi-head attention implementation as derived from Meta ESM, and its OpenFold subdirectory and EMA helper as OpenFold code. The inherited attention header contains an unresolved `XXXX-10` placeholder; that original header is preserved. The verified upstream origin and full license texts are provided here:

- [Meta ESM MIT notice](THIRD_PARTY/ESM-MIT-LICENSE.txt), verified against the [official attention source](https://github.com/facebookresearch/esm/blob/main/esm/multihead_attention.py) and [MarS-FM repository map](https://github.com/valence-labs/mars-fm#repository-structure).
- [OpenFold Apache-2.0 license](THIRD_PARTY/OpenFold-Apache-2.0.txt); copyright notices remain in the original source files.
- [Three.js license](studio/static/vendor/THREE-LICENSE) accompanies the bundled viewer.

mdCATH-derived coordinates in Studio retain attribution to Mirarchi, Giorgino and De Fabritiis, *mdCATH: A Large-Scale MD Dataset for Data-Driven Computational Biophysics* (Scientific Data, 2024), [DOI:10.1038/s41597-024-04140-z](https://doi.org/10.1038/s41597-024-04140-z), under CC BY 4.0. Studio selects, aligns and reformats the simulation coordinates for display. Model predictions are separate derived outputs.

Weights and bulk trajectories are downloaded separately using the pinned release receipts. Model and dataset terms apply separately from the wrapper’s software license.
