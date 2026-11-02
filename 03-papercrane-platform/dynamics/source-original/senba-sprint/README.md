# SENBA experiment sprint

Working local toolkit for auditing the released SENBA model, evaluating paired
endpoint samples, and planning experiments within a $30 compute ceiling.

The revised scientific plan is in [SCIENTIFIC_REVIEW.md](SCIENTIFIC_REVIEW.md).
The separately frozen real-data workload is in
[FROZEN_EVALUATION_PROTOCOL.md](FROZEN_EVALUATION_PROTOCOL.md).
The final result interpretation is in [RESULTS_SUMMARY.md](RESULTS_SUMMARY.md).

## Current capability

- Fetch the exact public `vkali08/senba` snapshot and verify weights and receipts.
- Recompute published receipt arithmetic without confusing it with raw replication.
- Analyze existing paired coordinate ensembles, with source/candidate matching,
  per-protein summaries, individual training-seed results and paired bootstraps.
- Compute original centroid RMSD, sample error, spread, finite-K diagnostics and
  exploratory energy score. Endpoint MSE and distributional quality use separate diagnostics.
- Validate experiment metadata, produce an inert job plan, and account for reserved
  versus billed costs using an atomic local ledger.
- Extract hash-pinned public mdCATH frames and run paired source/SENBA inference on
  Modal against pinned public checkpoints and source code.

The real `1e7uA04` technical pilot and all seven other panel jobs have completed.
Its Modal application is
[ap-OFWoTF9AIsGeU8eNkGeTjM](https://modal.com/apps/hpoonepa-42439/main/ap-OFWoTF9AIsGeU8eNkGeTjM),
and all eight K=16 augmentation jobs also completed. Across the 16 stopped
applications, the evaluation generated 5,120 structures and receipts show zero
active tasks.

This workload covers eight previously used validation proteins, 20 transitions per
protein (five replicas times four starts), prefix-preserving K=4, K=8 and K=16
paired samples per model, ten ODE steps, and only the released seed-1 candidate.
At K=16, equal-protein endpoint centroid RMSD is 10.04243879 angstrom for source
and 10.02861107 for candidate, a -0.01382772 angstrom candidate-minus-source
difference (about 0.138%) with improvement on 8/8 proteins. Energy score differs
by -0.00642231 angstrom, with conditional protein-bootstrap interval
[-0.01166227, -0.00159859] and improvement on 7/8 proteins.

The endpoint gain magnitude falls 42.4% from K=4 (0.02400558 angstrom) to K=16,
so finite-K choice materially affects the estimate. This is a conditional endpoint
diagnostic from one training seed on a reused validation panel, using a new
evaluator at the fixed temperature and lag. See
[RESULTS_SUMMARY.md](RESULTS_SUMMARY.md) for the evaluation scope and sampling interpretation and
[the K=16 report](artifacts/reports/sampling-k16-v1/results.md) for the final merged
analysis.

## Run locally

From this directory, use Python 3.10+ with NumPy. On this machine, the existing
`/Users/harsha/anaconda3/bin/python` already has the required packages.

```sh
python -m pytest -q
python -m senba_sprint demo --output artifacts/synthetic-demo.json
python -m senba_sprint preflight configs/sprint.json
python -m senba_sprint plan configs/sprint.json --output artifacts/job-plan.json
```

`demo` generates synthetic fixtures for software-contract checks.
`preflight` currently exits 2 and identifies missing inputs. Existing result files
are never silently overwritten; choose a new output filename for a rerun.

Download the release using the immutable revision embedded in `release.py`:

```sh
python -m senba_sprint.release --destination artifacts/hf-release --with-checkpoint
python -m senba_sprint.audit --release-dir artifacts/hf-release --output artifacts/receipt-audit.json
```

The fetcher's nonzero status can indicate a completed audit with a mismatch, not
an incomplete download. Inspect `release-snapshot.json`. The downloaded README
currently differs from the hash in its own upstream manifest; preserve both for
the audit. The selected checkpoint's independently recorded expected hash is
`f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c`.

## Coordinate input contract

`python -m senba_sprint analyze pairs.jsonl --output artifacts/analysis.json`

Each JSONL object is one physical transition and one inference batch:

| Field | Meaning |
| --- | --- |
| `protein_id`, `replica_id`, `start_id` | Strings identifying the observed transition |
| `training_seed` | Actual integer RNG seed encoded as a string, not its ordinal label |
| `inference_seed` | String identifying the sampling RNG configuration |
| `units` | Exactly `angstrom` |
| `alignment` | Exactly `start_aligned`; align using the frozen original evaluator |
| `start`, `target` | C-alpha coordinates `[N, 3]` in the common start frame |
| `source`, `candidate` | Matched generated coordinates `[K, N, 3]`, K at least 2 |

The atom order and mask must be identical, and coordinates must be finite. All
training seeds must cover the same proteins and physical transitions. Reusing an
inference ID across training seeds requires identical source draws. Distinct draws
need distinct IDs. The analysis averages repeated draws within a transition before
protein averaging, preserving the original transition and protein analysis units.

Negative candidate-minus-source differences favor the candidate for error metrics
and energy score. Ensemble spread has no intrinsically favorable direction.
Energy score and finite-K correction assume independent conditional samples for
their unbiased interpretation; the sampler's provenance must support that assumption.

No automatic target superposition is performed: separately optimizing sample-to-target
alignments would change the squared-error decomposition and energy-score geometry.
The source/candidate pairing and common frame must match the published evaluator
before any raw-coordinate result can be called a reproduction.

## Unavailable inputs and original-roadmap boundary

The public release includes the chosen seed-1 interpolated checkpoint and summarized
receipts, but does not list the raw evaluation arrays, the adaptation code, the
train/validation CSVs or original seed-2/seed-3 checkpoints. The user has confirmed
that these missing assets are not available. The absent items are:

1. Original `baselines/mars_fm` adaptation and evaluation repository and its revision.
2. `adaptation_data/128x32/train.csv` and `val.csv`, underlying validation trajectories,
   or the original paired generated arrays and start/target metadata.
3. Seed-2/seed-3 parent or selected checkpoints (training RNG seeds 20260826/20260827).
4. Original raw arrays and evaluator receipts needed to establish exact reproduction.

The public training receipt records train CSV SHA-256
`ce2c0f3408e4934161535b519552d72f27c7e4d8973cb9fa55a4cebce014bba4` and val CSV SHA-256
`311704d26216300bc6606546e6699a3a3efce676497ed5177a639fde1175f799`.
The combined subset manifest hash identifies the subset manifest. Supply the
individual trajectory-file hashes separately when completing the config.

G1 is complete as the eight-protein public-data seed-1 evaluation, and the G3 sampling-size sensitivity
component is complete. Original G2 additional-training-seed experiments, the G3
training comparator and G4 frontier experiments are **not done** because their
required assets are unavailable. None of the completed sampling jobs should be
relabelled as those experiments.

## Budget policy

`BudgetLedger` requires spent + commitments + new reservation + $10 reserve <= $30.
Failed runs keep their reservations until actual charges are reconciled. Completed
IDs cannot be reused as fresh runs. Concurrent writers use a file lock and atomic
replacement. Charges that consume the reserved margin freeze further reservations.
This only constrains callers that use the ledger; provider charges can arrive late.

Provider-reported charges total $4.56762390: $1.23086024 for K=4 and $3.33676366
for augmentation. The ledger retains a $2 late-billing allowance and preserves the
untouched $10 reserve. All 16 applications are stopped with zero active tasks, and
no further jobs are queued. The sealed test split remains reserved; release publication and manuscript
submission are separate stages.
