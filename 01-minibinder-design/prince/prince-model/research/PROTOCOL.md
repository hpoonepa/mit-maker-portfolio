# PRINCE site-selection experiments, 2026-10-11

Objective: rank useful target surface sites before binder generation. This is not a binder-sequence or affinity predictor.

The installed runtime model remains frozen. This file preserves the dated research protocol. In this repository, source coordinates are read from `.cache/benchmark/cif`, the corrected manifest is in `data/eval/`, and new experiment outputs go to `PRINCE_DATA_DIR` (default `work/`).

## Experiment 1: richer features and task-aligned learning

Use the existing connected-component membership: 340 training, 139 validation, 110 historical test interfaces. Train only on training labels. Select on validation, using component-macro top-1 majority-patch hit, then top-3, then top-10. Write the selected configuration before test evaluation. Test is a retrospective comparison, not a newly untouched holdout; no tuning against its outcomes. The original split does not ensure homology independence.

Keep the original surface patch generator and its 3–12 residue footprints for the controlled comparison. Measure the candidate-pool oracle: whether any enumerated patch could satisfy the existing success definitions. Do not shrink patches or redefine success to inflate results. Preserve Jaccard 0.5 suppression and exact label denominators.

Controls: exposure-only and the frozen four-feature linear scorer. Candidate models: nonlinear residue models with four versus enriched features; direct patch classifiers, regressors, and learning-to-rank models using enriched target-only features. A small predeclared grid uses tree depths 2/4 for residue/classifier/regressor models and 3/5 for ranking models, 200 trees, fixed random seed 17. Rich features include residue identity, chemical classes, multiscale target-only geometry and local surface composition. No antibody atoms, epitope labels, residue identifiers, or target identifiers enter features.

Report top-1/3/5/10 majority-patch hit and half-epitope recovery, both counts and component means. Report paired component-bootstrap intervals against the incumbent. Verify that the regenerated incumbent reproduces the frozen site results. Any differences must be disclosed rather than hidden. Runtime adoption requires a meaningful validation result and a consistent historical test result; a trained model is not automatically promoted.

## Minibinder data research

Antibody epitopes are a proxy task. Identify public measured minibinder datasets and distinguish measured binding from predicted interface locations. Binding failures are not definitive negative site labels: sequence, fold, expression, and assay can cause failure at an otherwise usable site. Prefer experimentally solved interfaces for a clean site benchmark; positive binders with predicted interfaces can support a separately marked weak-label dataset. Split by target homology and design lineage, not random designs.

## Input audit amendment, before any model training

The first cache pass reproduced `GeometricArm._exposure`, revealing that it passes only `antigen_chains[0]` as `focus_chain`. `compute_burial` explicitly restricts returned residues to that chain. This loses labeled residues in 93 training, 44 validation, and 19 test interfaces (956/604/197 labels, respectively). The original residue-feature training used all antigen chains, so the site-evaluation input universe was narrower than the trained residue universe.

Retain this original cache and its receipt. Regenerate a separately versioned `cache_full_antigen` with no single-chain focus after `load_antigen` has already removed antibodies and trimmed around ALL declared antigen chains. Use all declared antigen chains for new training/inference. Report the original incumbent, the same incumbent on the repaired candidate universe, and the validation-selected learned model separately. This change was triggered by an input-integrity assertion, before fitting or inspecting model validation scores. It is a coverage correction, not a tuned threshold.

## Reproducibility

Record source and coordinate hashes, package versions, all candidates and validation scores, the locked winner, errors, split counts, and limitations. Downloads retain upstream licenses. Paid remote compute is not part of this initial local experiment.

## Amendment 2, 2026-10-11: random control, top-3 endpoint, and scale-up

**The missing control.** No prior PRINCE benchmark included a random-patch-selection
control. Added (`random_control.json`, 400 reps under the identical NMS and
denominators). Result: the shipped ranker is indistinguishable from random at every k
on cluster-macro majority-hit (z = +0.0/+0.1/-0.5/-0.3), and exposure-alone is *worse*
than random at top-5/top-10 (z = -1.8/-2.3). The previously advertised "69/110
majority-hit at top-10" is the random-chance rate. Every future report of a ranking
metric must carry the random control beside it.

**Endpoint change to top-3.** The primary endpoint becomes cluster-macro
majority-hit@3. `selection_lock.json` (top-1 primary) and its test read stay in the
record. `relock_top3.py` re-ranks the SAME validation table by @3; that is an
EXPLORATORY re-analysis, not a pre-registration, because the test split had already
been read under the first lock. It is reported as hypothesis-generating only. Its
winner (`patch_regressor_enriched_d2`, best on validation at 0.428 vs random 0.227)
scored z = -0.1, p = 0.54 on test: exactly random.

**Why both locks failed to transfer.** The metric is a macro-average over antigen
clusters, and the splits hold only 116 / 39 / 34 clusters. At an effective n of 34 the
random-control sd is 0.050-0.060, so selecting among 12 models at 4 operating points
selects noise. This is a power failure, not a modelling failure, and no richer model
can fix it at this sample size.

**Scale-up (critical path).** The manifest holds 6,937 interfaces across 1,549
clusters (train 4760 / val 1057 / test 1120); the experiment used 589 across 189.
`build_cache_all.py` builds `cache_all/` over the full manifest with identical feature
semantics (same 51 features, same order, same `focus_chain=None` fix), verified
numerically identical on shared contexts. Expected ~14x training data and ~8x test
clusters, cutting the noise floor by roughly 2.8x. Cluster disjointness across splits
and per-instance label identity are asserted, not assumed.

**New feature blocks, permissive-licence only.** PRINCE must ship under an
OSI-approved licence, so the shipped model may be built only from permissively
licensed inputs: our own geometry, ESM2 embeddings (MIT), ProteinMPNN inverse-folding
statistics (MIT). PeSTo is CC BY-NC-SA 4.0 (NonCommercial + ShareAlike) and is
therefore a COMPARATOR ONLY, run out-of-tree; it must never become a feature source,
or the model becomes a derivative work and the entry is ineligible. ESM-IF1 weights
(CC-BY-NC) are excluded for the same reason. The atom-level geometry block is
implemented independently from standard structural-biology descriptors, with the
PeSTo source treated as off-limits.

**Next pre-registration (binding, to be written before any test read).** Once
`cache_all/` and the feature blocks exist: a single fresh sweep, primary endpoint
cluster-macro majority-hit@3, model and feature-block selection by grouped
cross-validation over the TRAIN clusters only (not the single val split), one locked
winner, then one test read. Report the random control and the paired cluster-bootstrap
CI against both the incumbent and exposure. Also report the candidate-pool oracle, so
ranking skill is never confused with pool coverage.
