# SENBA sprint: Astra review and corrected protocol

Reviewed by a gpt-6-astra subagent at the user's request, 4 September 2026.
Implementation delegated to gpt-5.6-sol and gpt-5.6-terra. This review supersedes
the scientific gates and budget estimates in the earlier nine-page sprint PDF.
It evaluates the supplied plan and reported draft findings; it is not a raw-data
replication, peer review, or certification of the model.

## What changed

1. **Sample MSE does not validate a distribution.** Reducing predictive spread can
   improve both centroid and individual-sample squared errors. Preserve the
   original centroid RMSD as the primary metric; add squared-error decomposition,
   ensemble spread, and an exploratory energy score in the fixed coordinate frame.
   Geometry, diversity, accuracy, and distributional agreement are different claims.
2. **Use Euclidean distance, not squared distance, in the energy score.** For K
   conditionally independent samples, use mean distance to target minus half the
   unbiased off-diagonal pairwise mean distance. Here distance is RMS Euclidean
   coordinate distance normalized per atom. K=4 is noisy and cannot establish
   calibration. Correlated/tree samples require a different assessment of bias.
3. **Respect the original coordinate gauge.** All predictions and the target must
   already be aligned to the same start using the original pipeline. Do not align
   individual samples to the target during scoring. The identity is
   sample_MSE = centroid_MSE + ensemble_variance, in squared angstroms.
   Centroid error to one realized target is not an estimate of biological bias.
4. **Expose finite-K uncertainty.** The diagnostic
   centroid_MSE - ensemble_variance/(K-1) estimates population-mean error to that
   realized target under iid sampling; it can be negative. Subsets of the original
   four draws show sensitivity, not independent replications. Increase K only on
   a panel selected before seeing new outcomes, when measured cost permits.
5. **Report seeds separately.** Proteins and training seeds are crossed. Resample
   the same protein indices across seeds for a joint protein bootstrap. Three
   training runs do not justify precise population-level training-seed intervals.
   Repeated inference draws are not additional independent proteins.
6. **Validation remains reused.** Freezing this sprint cannot undo earlier alpha,
   panel, metric, or checkpoint selection. New validation CIs remain conditional
   and exploratory. Keep the existing 495-domain test set sealed during development.
7. **Lag rescoring is only a mismatch diagnostic.** Scoring lag-50 samples against
   t+25 and t+100 targets does not establish learned specificity or horizon transfer.
   Verify saved-frame interval, physical time, positive offsets, and same-replica
   continuity before any such analysis. Defer new-lag retraining.
8. **Add an ordinary conservative-training control.** A reduced learning rate with
   the same training data/steps, or an existing early checkpoint selected by update
   norm without its endpoint score, is a more useful comparator than a random or
   reversed parameter vector. The current evidence does not prove interpolation
   necessary or novel.
9. **Retention gates are limited evidence.** Preserve the seven original thresholds,
   degradation signs, and eight-protein selection history. Report uncertainty and
   every failed gate. The 7.35%/7.5% distinction may reflect Monte Carlo noise.
   Avoid declaring a sharp safe boundary or preserved conformational distribution.
10. **The earlier budget was mis-added.** Its ranges summed to $39-$67. Neither the
    reported $19.45 prior campaign nor 122-second training run prices the proposed
    inference work without receipts. Obtain a timed pilot and verified rates first.

## Revised order and release gates

| Stage | Work | Gate |
| --- | --- | --- |
| G0 | Check repository/model/data revisions, atom masks, split, lag units, seeds, receipts; reconstruct saved summary and one raw row | Match published rounding precision and explain every discrepancy before dependent runs |
| G1 | Original RMSD, decomposition, finite-K sensitivity, exploratory energy score, per-protein outputs | Complete paired records; numeric identity closes; no missing-data exclusions hidden |
| G2 | Fixed 7.35% candidate from seeds 2 and 3 on the full 28-protein panel | Measured pilot fits remaining budget; matched starts, sampling and targets |
| G3 | Conservative-training comparator and prespecified sampling check | Freeze selection rule and configuration before inspecting outcomes |
| G4 | Small fully reported alpha frontier | Existing retention tolerances unchanged; cost permits full evaluation of selected points |
| Optional | Structural strata; explicitly labeled lag mismatch diagnostic | Exploratory only; avoid coupling gain with source error as a mechanistic claim |

For every release: spent + outstanding commitments + conservative new-job
estimate + reserve must be at most $60. Startup, idle GPU time, CPU/RAM, storage,
egress, retries and failed attempts count. The local ledger is not a provider
billing hard cap. Provider workspace budgets and actual invoices must be checked.

## Attainable paper claim

A documented accuracy-retention tradeoff for one exact-lag adaptation of a
protein model, with a small endpoint improvement and explicit limitations from
validation reuse, sampling, temperature and panel size. Better experimental
results may support stronger claims; the present plan cannot guarantee them.

The acceptance percentages in earlier advice were subjective guesses without
calibrated supporting data. They should not be used to justify spending or claims.

## Remote execution assumptions to verify

Modal execution timeouts apply per attempt and exclude scheduling; startup has
its own timeout. Keep retries explicit and container concurrency bounded. Account
for cold starts and idle containers when estimating cost.

- [Modal timeouts](https://modal.com/docs/guide/timeouts)
- [Modal scaling controls](https://modal.com/docs/guide/scale)
- [Official MarS-FM code](https://github.com/valence-labs/mars-fm)

The source and dataset links published in the local blog are
`valencelabs/mars-fm` and `compsciencelab/mdCATH`. These are discovery hints;
they do not identify the user's SENBA parent checkpoint revisions or split.
