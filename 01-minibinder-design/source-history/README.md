# Original campaign source

These are snapshots of the original development files, with source comments and research credits retained. The unversioned campaign folders are preserved as snapshots.

| Directory | Role |
|---|---|
| `campaign-scripts/` | Early DWV VP3 and RBX1/2LGV design, folding and filtering iterations |
| `config/`, `src/`, `validators/`, `tests/` | Original settings, objective adapters, consensus analysis and software checks |
| `scripts/` | Colab/API clients, sequence assessment, post-assay ranking and modeling utilities |
| `scripts/egfr_pilot/` | Separate EGFR simulation pilot retained as a learning experiment |
| `nebius/` | SSH campaign/checkpoint runner, validation and selected output summaries |
| `runpod/` | Tri-model scoring worker and container/launch setup |
| `vast/` | GPU instance orchestration, monitoring, resume and earlier campaign entry points |
| `Proteinbase Analysis.ipynb` | Exploratory binder-metric analysis |

The DWV story and what was actually measured are in the [pipeline notes](../docs/PIPELINE-NOTES.md). Earlier RBX1 and EGFR work is retained as separate learning experiments. Historical comments record the hypotheses used in those iterations; the assay records contain the measured outcomes. [Citations](../CITATIONS.md) clarify adapted metrics and external dependencies.

Some scripts need workspace-specific files, scientific packages, GPU assets or separately configured cloud accounts. No model weights or credentials are supplied. Original files and Git histories remain preserved outside this public copy.
