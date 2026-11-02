# MarS-FM mdCATH adaptation protocol

Status: frozen development protocol; no final-model or state-of-the-art claim.

Frozen on 2026-07-31 before inspecting the first adapted checkpoint's
structural or exact-lag benchmark outputs.

## Scientific question

Can the pinned public MarS-FM checkpoint be adapted on the standard mdCATH
training split so that it preserves its strong equilibrium-ensemble behavior
while becoming a useful predictor of observed, same-replica lagged
transitions?

The two development objectives are separate:

- `msm`: reproduce MarS-FM's state-balanced transition sampling;
- `exact_lag`: use observed `(t, t + 50 frames)` pairs from one replica, with
  starting-state cluster balancing and no replica crossing.

The exact-lag objective is a DynaView development contribution. It is not a
validated kinetic model unless it passes the kinetic gates below.

## Frozen identities and data boundary

- MarS-FM source code commit:
  `4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946`.
- MarS-FM model revision:
  `1e957cd4b9f1a054ceb0c2104f40ba6f3cc0d8d0`.
- Source checkpoint SHA-256:
  `f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879`.
- Standard split semantic SHA-256:
  `53e81a90c0dcf3e00a814744f62d25db52f5aa8790475294dac451d36d728b8b`.
- Development subset semantic SHA-256:
  `163ab0043d86b5a2731e1b1a233af27fb069049897d657fd5c39bd54b1343b3f`.
- Development subset: 128 train and 32 validation domains, all five 450 K
  replicas, with byte-bound source and converted-array receipts.
- Standard test records opened during adaptation and selection: zero.

All validation transition items are materialized once. MarS-FM's stochastic
flow noise and interpolation times are replayed from a dedicated validation
seed, and the caller's training RNG state is restored afterward. Source loss
is evaluated twice and must replay within `1e-6` before a run is valid.

## Development scorecard

### Transport-loss gate

A checkpoint may enter molecular benchmarking only if its best loss is lower
than the untouched source model on the identical validation transitions and
identical flow randomness. Training loss alone is never a gate.

### Observed-transition gate

Use fixed same-replica transitions at exactly 50 frames. For each transition,
score persistence, the mean error of individual stochastic samples, best of
K, the ensemble-mean endpoint, displacement-magnitude error, and displacement
direction cosine after the same C-alpha alignment policy.

Before any standard-test access, a candidate must on the validation suite:

1. improve ensemble-mean endpoint RMSD over the pinned source MarS-FM model;
2. beat persistence with a protein-level 95% bootstrap confidence interval
   excluding zero;
3. improve on a majority of validation proteins, not only pooled transitions;
4. retain the result for at least three training seeds.

Best-of-K is diagnostic only because it uses the unknown future to select a
sample.

### Equilibrium-ensemble retention gate

On matched tree samples and MD references, report DCCM error, RMSF error and
correlation, pairwise-distance Wasserstein distance, reference-PCA covariance
error/RMSIP, contact-transition Wasserstein distance, radius-of-gyration
Wasserstein distance, and clash rate. A kinetic gain cannot promote a model
that materially degrades the source model's equilibrium or structural
behavior. The one-protein `1e7uA04` comparison is a development pilot only;
promotion requires a protein-level validation aggregate.

## Promotion boundary

Passing this protocol only freezes a candidate. The 495-domain standard
mdCATH test split remains unopened until architecture, checkpoint, sampling
settings, seeds, metrics, and failure policy are immutable. A field-level
claim additionally requires matched runnable baselines, protein-level
uncertainty, replica-noise comparisons, and independent external replication.

