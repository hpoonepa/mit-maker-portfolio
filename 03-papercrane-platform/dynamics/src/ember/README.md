# Ember Pocket

A small cryptic-site ranker built on frozen protein features and explicit
conformational evidence. This is the September 28 implementation of the
[September 24 master specification](../../plans/ember-pocket-master-build-plan-2026-09-24.md).

**Current state:** model, training and inference code implemented; local software
contracts checked. The model is untrained. Embedding generation, GPU/cloud
execution and predictive evaluation remain pending.

The complete next-stage protocol is in
[the implementation and compute plan](../../plans/ember-pocket-implementation-and-compute-plan-2026-09-28.md).
[The source audit](research/README.md) records the papers, commits, actual release
inventory and corrections to the older pipeline.

## Model

```text
sequence → frozen ESM-2 150M → R0 residue head ───────────────┐
apo chain → verified residue map → apo pocket candidates ──┼→ S0 static ranker
sequence → frozen BioEmu → accepted all-atom conformers ───┘       +
                         → per-frame pockets → site statistics → E0 correction
                                                                ↓
                                               three distinct site hypotheses
```

R0 is a 640→256→128→1 MLP with input LayerNorm. Its analytical parameter count is
198,401, computed from the architecture; runtime parameter verification is pending. S0 starts linear. E0
starts as a zero-initialized linear correction with S0 frozen. Small MLP rankers
and an explicit-support-count ablation are implemented as alternatives. GVP and
generator fine-tuning are deferred.

Output scores rank annotation-recovery evidence. Binding probabilities, affinities,
kinetic rates, populations and experimental site validation require separate
measurements. BioEmu conformations are unordered, sequence-conditioned samples.

## What is implemented

| Component | Coverage | Runtime status |
| --- | --- | --- |
| Strict targets/references/predictions | IDs, hashes, partitions, masks, statuses | Local contract checks |
| PDB/mmCIF mapping | Explicit chain/model, canonical gaps, insertion codes, exact ligand | Synthetic and three public structure fixtures |
| fpocket/P2Rank/Lacuna parsers | Real upstream file schemas, residue mapping | Public output fixtures; tools not run |
| Site grouping | Complete-link overlap, medoid, cap, per-frame deduplication | Local contract checks |
| Features/caches | Static/ensemble separation, missingness, train-only normalization, hashes | Local contract checks |
| Quality/alignment | Proper rotations; CA/sidechain/gross-clash screens | Local contract checks; thresholds provisional |
| R0/S0/E0, training/resume/inference | Cached features, development selection, gated execution | Authored and syntax checked; **model tests deferred** |
| Evaluator/reports | One-to-one top-k, failure denominator, family bootstrap | Local contract checks |
| Cost ledger/command plans | Reservations and no-launch plans | Local contract checks; provider billing controls separate |
| Data ingestion/splits | Author annotations, official split guard, OOF lineage, similarity-edge audit | Schema/fixture checks; full cohort not frozen |

## Run local checks

From the Dynamics directory (`03-papercrane-platform/dynamics`), using a Python environment with NumPy and Biopython installed:

```bash
PYTHONPATH=src python -m unittest discover -s src/ember/tests -t src -v
PYTHONPATH=src python -m ember.verify_local --output /tmp/ember-local-checks.json
PYTHONPATH=src python -m ember plan
PYTHONPATH=src python -m ember research-inventory
PYTHONPATH=src python -m ember sampling-plan --sequence ACDEFGHIK --output-dir /tmp/ember-example
```

The last command emits an inert argument plan with a synthetic example sequence,
leaving execution and output-directory creation to the later run stage. Local checks require NumPy and Biopython; their
tested versions are recorded in `requirements-local.txt`. The checks used the existing
environments without package changes.

Use the same compatible Python environment for the CLI and contract checks.
The receipt records the interpreter and dependency versions used for each check.

The separate `model_checks/run_checks.py` executes PyTorch models. It is outside
the local test suite and remains **unrun**. Training and prediction commands
refuse execution unless their explicit `--execute-model` flag is supplied in a
later user-authorized session. No command provisions a provider instance.

## Data and leakage boundary

- All internal residue indices are zero-based positions in the full canonical
  sequence. Original author chain/number/insertion code is preserved separately.
- The source inventory confirms 885 training apo structures and 222 test apo
  structures. Training annotations and split metadata are cached. Test annotations,
  foundation weights and the 1.15 GB structure archive were not downloaded.
- `PreparedTarget` bundles contain inputs, sites, features and provenance only.
  Reference labels are separate. Training rejects test/external examples.
- Three-fold cross-fitting keeps scored training groups out of R0 fitting **and
  early-stopping selection**. Final development results still drive selection;
  held-out performance is measured by frozen public/external test evaluation.
- OS-level isolation requires the future inference worker to mount only inputs
  and checkpoints and write predictions; reference storage stays on the
  evaluation worker.

## Primary comparison

Macro per-protein annotated-site recall@3, with maximum-cardinality one-to-one
matching at residue Jaccard ≥0.25. Final predictions are deduplicated at Jaccard
≥0.5. Missing/failed eligible predictions are misses. Invalid references are
pre-freeze protocol errors. Negative controls have a separate denominator rather
than artificial perfect recall. Candidate coverage, ranking conversion, residue
AP and selected-conformer geometry are separate diagnostics.

Use native end-to-end baselines and matched-candidate ranking comparisons as two
different tables. Label a static scorer given ensemble-generated proposals as an
ensemble-proposal method. Author PR-AUC definitions and this implementation's average
precision are also separate metrics.

The inexpensive Lacuna NMA/alpha/learned baseline and mean cached R0-logit ranker
are required controls. Pin Lacuna's backend explicitly, preserve its run receipt,
and keep its prior public-test exposure visible. The independent run receipt supplies the generator, input and
configuration identity alongside the saved report.

## Next execution boundary

Before model work: review the plan, select a provider/environment if needed,
authorize the stage, run deferred CPU model checks, verify local checkpoint
hashes, audit original data and run a few development-only external-tool smoke
targets. Freeze quality thresholds, relatedness rules and measured costs before
bulk sampling. The prior USD 200 amount remains a proposed cap; stage authorization and
measured comparator costs precede spending.

See [the original work log](../../source-original/dynamics/ember/WORK_LOG.md) for decisions and `artifacts/` for the generated plan/readiness
and verification receipts. Historical `src/legacy_poc/*.py` code is not imported by this
implementation.
