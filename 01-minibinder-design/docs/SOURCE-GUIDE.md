# Source and setup

The main project is the DWV VP3 campaign. The source retains several iterations, with their original scientific references. It is a campaign record plus a small Python dispatcher: individual scripts keep their own inputs and parsers, and some historical jobs require original workspace files. The [pipeline notes](PIPELINE-NOTES.md) explain chronology and measured results; [CITATIONS.md](../CITATIONS.md) identifies upstream tools and data.

| Path | Purpose |
|---|---|
| `src/minibinder/prepare/` | DWV candidate lists and hotspot-contact inspection |
| `src/minibinder/design/` | Fixed recipes, YAML-configured V5 driver, scoring objective and loss adapters |
| `src/minibinder/fold/`, `score/`, `filter/` | Independent prediction, consensus metrics, retrospective ranking and candidate filters |
| `backends/` | Modal, Nebius, RunPod and Vast launch/checkpoint/collection code |
| `config/` | DWV default and hotspot settings; the target coordinate input must be supplied |
| `notebooks/` | Colab/API campaign clients, expression-oriented sequence checks and scoring |
| `tests/` | Focused scoring tests and Nebius orchestration tests |
| `legacy/` | Earlier VP3 campaign compilation, prediction clients and candidate tables |
| `source-history/` | Original campaign scripts and backend snapshots; see its archive map below |
| `results/5g51/`, `results/bli/` | Candidate provenance, computational metrics and experimental exports |
| `prince/prince-model/` | Structural checks, separate saved site ranker, research code and frozen evaluation |
| `prince/prince-webapp/` | Browser workspace and evaluation pages; uses the adjacent Python service |

The RBX1/2LGV recipes are retained as earlier learning experiments. The `source-history/scripts/egfr_pilot/` directory is a separate EGFR simulation pilot, not evidence for the DWV result. Cloud launchers are executable infrastructure code and can incur charges when configured and run; reading or testing the scoring functions does not start them.

## CPU checks

Use Python 3.11 or newer from this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest tests/test_tri_objective.py tests/test_consensus_rank.py
minibinder --list
minibinder score rank --selftest
```

The ranking rules were derived after the assays from one observed positive; passing software tests does not validate those rules prospectively. The optional `confide_score` function remains an explicit `NotImplementedError` research stub, not a completed feature.

## Design and independent prediction

The heavy scientific work comes from [Mosaic](https://github.com/escalante-bio/mosaic) and its upstream models. Install the intended checkout with its `uv` dependency resolution or use the recorded backend container setup. **The PyPI package named `mosaic` is unrelated**, and this portfolio package does not install GPU models.

```sh
minibinder design v5 --seed 42 --config config/v5_5g51_hotspots.yaml
```

This is a configured GPU job, not a CPU demo. It needs the target coordinates named in the configuration, upstream dependencies/model assets and an appropriate GPU environment. Backend guides retain historical commands and versions; credentials and upstream weights are not included. Model-specific terms, especially Protenix-v2 weights, remain separate from the wrapper code license.

## PRINCE

Follow the companion [model README](../prince/prince-model/README.md) and [web README](../prince/prince-webapp/README.md). The web worker uses the lightweight residue model. The 400-tree site ranker is a separate command operating on prepared features:

```sh
# From prince/prince-model, after its documented installation:
preflight analyze local-target.cif --chain A --top 3 --json analysis.json
prince-rank examples/patches.json --top 3 --output ranked.json
python scripts/verify_artifacts.py
python -m pytest -m 'not network'
```

The browser interface requires Node >=22.12 and the sibling Python service; `npm run verify` checks types, builds and checks links. The historical demonstration recording (submitted separately) shows an earlier interface. Full training caches and upstream embedding weights are not bundled.

## Archive map and history

`source-history/campaign-scripts/` contains early DWV and RBX1 drivers; `src/` and `validators/` hold original objectives/validation; `scripts/` contains notebooks, retrospective analysis, the oral-delivery modeling experiment and EGFR pilot; `nebius/`, `runpod/` and `vast/` preserve compute integrations and selected saved summaries. These are source snapshots, not a claim of one portable workflow or per-file Git history.

The retained PRINCE release revisions are model `9a3551ba2be509809fe6657e3ebbd228eff86eb1` and web `58883bdce74b9599c87932a37e44bd9c4f12a2f8`. Their repositories include inherited iGEM starter-template commits, which are not PRINCE development. The separate `hotspot-preflight` precursor has its own real development history. Original histories and excluded branch files are preserved privately; this focused public copy does not invent a development timeline. See the portfolio's source inventory for copied paths.
