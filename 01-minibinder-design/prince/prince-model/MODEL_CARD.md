# PRINCE model card

This release contains two frozen models for different tasks. Neither predicts a binder sequence, affinity, or wet-lab success.

## Site ranker

**Artifact:** `src/prince_ranker/data/site_ranker.json`

**Runtime:** `prince-rank`, with the `ranker` extra

**Architecture:** XGBoost `binary:logistic`, 400 trees, depth 6, 660 inputs

The model assigns scores to candidate surface patches. Selection uses stable descending score order and suppresses a later patch when its residue Jaccard overlap with any selected patch is at least 0.5. Outputs are uncalibrated classification scores.

### Features

The feature matrix concatenates geometry (51 residue features), atom environment (104), and ESM-2 embeddings projected to 64 dimensions. Each block contributes mean, maximum, and population standard deviation over the patch. Three additional columns describe patch residue count, area, and radius of gyration: `51×3 + 104×3 + 64×3 + 3 = 660`.

The original summary described 52 geometry features and omitted the three patch descriptors. The ordered schema in this release follows `research/build_cache_all.py`, `research/build_atom_features.py`, and `research/sweep.py`, and corrects that description without changing the weights.

The embedding model is `facebook/esm2_t30_150M_UR50D`, revision `a695f6045e2e32885fa60af20c13cb35398ce30c`. PCA identifier: `57d5bd1fce5fedbc`. The projection was fitted on 4,457 training contexts and is included as `src/prince_ranker/data/esm_pca.json`. Its original metadata marks it provisional; do not replace it independently of the classifier.

### Data and selection

Labels were derived from SAbDab antibody–antigen interfaces using a 4.5 Å heavy-atom contact definition. Antibody atoms and epitope labels do not enter target features. The source snapshot and its hash are in `benchmark/snapshot/`.

- 6,127 contexts had the required features out of 6,464 built contexts.
- Fitting used 4,503 training interfaces across 1,047 antigen clusters.
- Negative patch sampling targets six negatives per positive, with a minimum of eight when available; evaluation uses the complete candidate pool.
- Selection used five-fold grouped cross-validation over training clusters, seed 17, with cluster-macro majority-hit@3 as the primary endpoint.
- The held-out evaluation contained 1,120 interfaces across 251 antigen clusters.

The original protocol and its amendments are retained in `research/PROTOCOL.md`. Earlier selections and negative findings are part of the study history. The test should not be described as untouched across the entire project's development.

### Results and interpretation

| Evaluation | Majority-hit@3 | Matched random control |
|---|---:|---:|
| Training-cluster cross-validation | 0.511 ± 0.033 across folds | See frozen CV receipts |
| Full held-out test | 0.508 | 0.233 |
| No training homolog ≥30% identity, 93 clusters | 0.458 | 0.238 |
| SAbDab2 40% clean criterion, 80 clusters | 0.439 | 0.261 |

Source records: [test results](evaluation/site-ranking/sweep_test_results.json), [homology subsets](evaluation/homology/subset_metrics.json), and [external split audit](evaluation/homology/sabdab2_arm_metrics.json).

The homology-clean result is the appropriate compact headline: approximately 0.44–0.46 top-3 majority-hit, with 0.18–0.22 improvement over the corresponding control. These are retrospective subsets. The two criteria define different populations and should not be pooled into a single estimate.

Random-control standard deviations describe random patch selection, not uncertainty across new target populations. A large standardized difference from that control does not replace a target-level confidence interval.

## Residue baseline

**Artifact:** `src/hotspot_preflight/model/prince_connected.json`

**Runtime:** `preflight analyze`, `preflight propose`, and `preflight serve`

**Architecture:** L2 logistic regression, regularization 1.0, intercept approximately −3.095

| Residue feature | Approximate fitted weight |
|---|---:|
| Exposure | +1.076 |
| Concavity | −2.304 |
| Hydrophobicity | −0.094 |
| Connectivity | +0.980 |

The connected manifest retained 6,937 interfaces in 1,549 antigen clusters. The cached-feature evaluation used 340 training, 139 validation, and 110 test interfaces, corresponding to 116, 39, and 34 clusters. These counts describe the baseline study, not the later site-ranker training set.

Test macro AUROC is 0.64790 (95% interval 0.62180–0.67218), compared with 0.64500 for exposure alone. Macro AUPRC is 0.13610. Metrics are computed per interface, averaged within cluster, then across clusters. The fitted and exposure-only baselines have similar AUROC in this evaluation.

## Intended use and limitations

Use PRINCE to inspect and prioritize target surfaces for further review. The benchmark measures antibody-epitope localization. Transferring site scores to measured minibinder outcomes did not produce a useful predictive result in the supplied study; a separately trained designability model was near chance. Minibinder affinity and success prediction require separate validation.

The structural service uses bound coordinates, limited candidate patches, and the metadata available in each input file. Missing assemblies, incomplete structures, unresolved residues, glycosylation, and conformational changes can alter the practical meaning of a site.

## Release provenance

The two trained model files are copied byte-for-byte from the supplied release package. Documentation and research paths were reorganized; workstation-specific prefixes in evaluation receipts were normalized to relative paths. Numerical results were not recomputed or modified. Consequently, historical source-code hashes describe the original experiment, while `ARTIFACTS.sha256` describes the redistributed files. Run `python scripts/verify_artifacts.py` to verify the latter.
