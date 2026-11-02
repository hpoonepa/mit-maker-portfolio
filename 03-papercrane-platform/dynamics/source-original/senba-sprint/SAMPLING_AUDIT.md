# Sampling-extension receipt audit

This is a read-only audit of the completed K=4 augmentation and derived prefix
artifacts, using saved records for all recomputations.

## Result

**PASS — 0 errors.** All eight augmentation runs completed their 60 expected
records, giving 480 augmentation records and 480 runtime receipts. Each of the
eight derived directories contains 20 records at each K prefix (4, 8, and 16),
for 160 records per prefix panel.

| Check | Observed result |
| --- | --- |
| Augmentation completion receipts | 8/8 `complete: true`, `transitions: 60` |
| Original / extra / runtime rows per protein | 20 / 60 / 60 |
| Derived K=4, K=8, K=16 rows per protein | 20 / 20 / 20 |
| Augmentation runtime rows | 480 |
| Source/candidate checkpoint identities in every extra record and runtime receipt | matched frozen source/candidate SHA-256 values |
| Paired RNG receipt | source and candidate before-state hashes matched, and after-state hashes matched, for all 480 rows |
| Block schedule | all original seeds were `20260904 + transition_index`; every extra block used exactly `+ block_id * 1000000`, for block IDs 1, 2, and 3 |
| Input receipts | every original and extra record's NPZ hash matched its local `inputs/<protein>.npz` SHA-256 and frozen spec |
| Frozen augmentation settings | all 8 specs: K=4 blocks, 10 ODE steps, 3 extra blocks, 600 s timeout, $2 reservation |
| Frozen code identity across augmentation jobs | all eight shared cloud hash `04c6ac…72217` and inference hash `4533c5…7f382` |

## Exact prefix preservation

For each of the 160 physical transition IDs, this audit reconstructed expected
prefix arrays from the stored original block 0 and extra blocks 1–3. It checked
exact byte-numeric JSON equality:

- Derived K=4 `start`, `target`, aligned source/candidate, and raw coordinate
  payload exactly equal the original stored K=4 record.
- Derived K=8 aligned and raw source/candidate arrays equal block 0 followed by
  block 1, with no re-sampling or reordering.
- Derived K=16 aligned and raw source/candidate arrays equal blocks 0, 1, 2,
  then 3, with no re-sampling or reordering.
- Every derived record's block IDs, per-block canonical record hashes, and source
  file hashes equal the audited input records.

The derived records also retained matching start/target coordinates, raw target,
units, alignment policy, evaluator and reproduction labels, target frame, data
receipt, upstream revision, checkpoint identities, and ODE settings across blocks.

## Report check

The local reports exist and each contains 160 records, eight proteins, one training
seed, and the indicated single K. Candidate-minus-source equal-protein deltas are
shown only as dependent sampling-sensitivity summaries:

| K | Centroid RMSD (Å) | Mean-sample RMSD (Å) | Energy score (Å) | Population-mean MSE estimate (Å²) |
| ---: | ---: | ---: | ---: | ---: |
| 4 | -0.024006 | -0.060260 | -0.003278 | -0.094958 |
| 8 | -0.018865 | -0.065167 | -0.006037 | -0.198510 |
| 16 | -0.013828 | -0.062934 | -0.006422 | -0.225901 |

K=4, K=8, and K=16 are nested on the same proteins, transitions, training seed,
and original draws. They are not independent replications, and the three report
intervals must not be compared as independent significance tests.

## Artifacts checked

- `artifacts/runs/augment-*-k16-v1/frozen-spec.json`, `completion.json`,
  `records.jsonl`, and `runtime.jsonl`
- Original K=4 records in `artifacts/runs/pilot-1e7uA04-k4-v2` and
  `artifacts/runs/panel-*-k4-v1`
- `artifacts/derived/*-k16-v1/k{4,8,16}.jsonl`
- `inputs/*.npz`
- `artifacts/reports/sampling-k{4,8,16}-v1/{analysis.json,results.md}`
