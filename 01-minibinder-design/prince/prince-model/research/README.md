# Research programs

Start with [the reproduction guide](../docs/reproducibility.md). `paths.py` defines `REPO`, `DATA`, and the frozen model path. Set `PRINCE_DATA_DIR` before running a study; it defaults to the repository's ignored `work/` directory.

| Program | Purpose |
|---|---|
| `build_cache_all.py` | Full connected-manifest geometry and patch cache |
| `build_atom_features.py` | Target-only atom-environment block |
| `build_esm.py` | Observed-residue ESM-2 embeddings and training-only PCA |
| `sweep.py` | Packing, grouped cross-validation, selection lock, test evaluation |
| `recovery_counts.py` | Interface counts for saved selection results |
| `split_homology_audit.py` | Similarity overlap and clean-subset analyses |
| `label_sampling_audit.py` | Label and sampling sensitivity |
| `crossmap.py`, `arm.py` | External SAbDab2 split mapping |
| `build_site_benchmark.py`, `score_site_benchmark.py` | Separate measured-minibinder transfer analysis |
| `run_pesto.py`, `residue_h2h.py` | Comparator execution and residue comparisons |

Other scripts preserve earlier experiments and sensitivity analyses. Read their module docstrings for input contracts. Missing caches and upstream models are explicit prerequisites, not bundled dependencies. Keep outputs separate from frozen `evaluation/` records.
