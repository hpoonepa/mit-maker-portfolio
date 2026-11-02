# Ember Pocket: research and benchmark protocol

Research date: 2026-09-24. Status: proposed protocol awaiting freeze and execution. Ember Pocket is the working name used in this memo for the pocket project previously called SENBA-Pocket. The model is untrained; benchmark evaluation and compute authorization are pending.

The recommendation is to establish an apo-only cryptic-site benchmark first, train a small frozen-embedding model second, and add a learned conformational correction only if it improves held-out development performance. The earlier [architecture proposal](senba-pocket-build-plan-2026-09-23.md) remains a source of implementation details; its GVP architecture and parameter count are candidates for development comparison.

## Scientific question and deliverable

Given a protein sequence and an explicitly selected unliganded (apo) structure, can Ember return three useful, distinct cryptic-site hypotheses more accurately per dollar than public alternatives?

Return site residue IDs, rank, supporting conformers when available, quality flags, and provenance. Site localization is the first task. Producing an open, useful geometry is a separate task. Binding affinity, druggability, kinetics, equilibrium occupancy and clinical value each require separate measurements.

Initially support folded soluble monomers, provisionally 80–350 residues, with reliable chain mapping. Fix eligibility from metadata before predictions. Report a restricted subset as such. A broader full-benchmark CPU baseline can coexist with a smaller, explicitly named ensemble track.

## Research findings and data choices

| Resource | Proposed role | What is verified and what remains |
| --- | --- | --- |
| [CryptoBench](https://github.com/skrhakv/CryptoBench/) | Main training, development and public test resource | Authors provide over 1,000 structures, split resources, a tutorial and baseline reproduction code. Complete data are linked through [OSF](https://osf.io/pz4a9/). Download, checksums, exact record counts and mapping audit remain to be done. |
| [CryptoBank paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC13267282/) | Candidate independent external test after overlap removal | Reports 5,151 cryptic sites across 3,643 clusters defined at 95% identity. Its many apo–holo–ligand combinations are correlated observations, not independent proteins. Labels use an automated structural crypticity model. |
| [CryptoBank source](https://github.com/Gervasiolab/CryptoBank) and [archive](https://zenodo.org/records/19099155) | Source and release acquisition | Primary research identifies public code/data resources. Archive contents and checksums were not inspected successfully in this research session. Confirm the exact experimental-apo subset before selection. |
| [PocketMiner](https://www.nature.com/articles/s41467-023-36699-3) original examples | Historical diagnostic | Audit overlap with all training and development data. Small, familiar examples are not automatically an independent test. |
| [BioEmu benchmarks](https://github.com/microsoft/bioemu-benchmarks) | Later conformational diagnostic | Separate from the site-ranking leaderboard; use the authors' applicable structural evaluation protocol. |

CryptoBench is the initial choice because it provides both training material and an established evaluation context. Do not train on everything and invent a random frame split afterward. Preserve its official test assignment. Create family-grouped development folds from official training data; do not move test relatives into training to balance the split.

Reserve an eligible, nonoverlapping CryptoBank cohort before any model tuning. Remove relatives of all Ember train/development proteins and document relatedness to the public test set. Its native 95%-identity grouping is too permissive for claiming unseen-family generalization. A proposed starting audit is sequence identity >=40% with >=80% coverage of the shorter chain, plus domain/structural similarity checks where possible. Remote homology requires additional sensitivity analysis. Record this relatedness heuristic and the results of those checks.

Keep duplicates, mutants, structures and conformers of a family together. Record generator and embedding-model pretraining exposure separately; unknown exposure remains unknown. Audit comparator training data too. For a CryptoBank-trained public model, establish the evaluation entries’ separation from its training data.

Exact denominators must come from the downloaded manifest. For example, the [sequence-based UniPocket paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC13477581/) reports evaluation on 193 retained CryptoBench proteins, illustrating why a paper's number is not automatically our denominator. Do not transplant filtered counts between studies.

The final dataset manifest needs: source/version/hash, protein and family IDs, apo model/assembly/chain, sequence, author residue IDs and insertion codes, canonical mapping, reference holo identity, exact ligand instance, annotated site residue sets, official partition, our development group, eligibility, exclusion reason and known training exposure. Reference structures and annotations are evaluation assets; the inference process must receive only the declared input.

## Models to compare

This public comparison suite is scoped to a staged $200 feasibility budget; select reproducible configurations after cost profiling.

| Method | Why include it | Comparison requirements |
| --- | --- | --- |
| fpocket and [P2Rank](https://github.com/rdk/p2rank) | Cheap geometric/chemical controls | Apo inputs; pinned versions; native site ranking. |
| CryptoBench pLM-NN | Strong sequence baseline for the dataset | Published encoder, checkpoint and preprocessing for reproduction; a matched-encoder variant for architecture attribution. |
| [Seq2Pocket](https://github.com/skrhakv/seq2pocket) | Recent public sequence-to-3D-pocket pipeline | Authors provide code, tutorials and a weights link. Verify which general/cryptic checkpoint is being evaluated and its training overlap. |
| PocketMiner and [AE-PocketMiner](https://github.com/bowman-lab/ae-pocketminer) | Learned structural cryptic-site methods | Preserve residue outputs; document any residue-to-site adapter. |
| [Lacuna](https://github.com/mooreneural/lacuna) | Direct ensemble-based site discovery/ranking alternative | Test a named public configuration. Include its relevant enhanced scoring configuration if reproducible and affordable; disclose omissions. |
| Frozen BioEmu + ordinary pocket scores | Isolates the value of learning the new scorer | Same cached conformers, filtering, candidate pool and site grouping as Ember. |
| Ember sequence, static and ensemble variants | Establishes what each component contributes | Same split, embedding backbone, tuning limits and evaluation cohort. |
| Sequence-based UniPocket | Additional relevant literature comparator | Local reproducible checkpoint/code availability was not established; do not fill its leaderboard row with an unrelated published score. |

Seq2Pocket smooths residue predictions and clusters solvent-accessible-surface points into sites. This makes it especially relevant: converting a residue classifier into a useful pocket shortlist is part of the actual problem. Its published framework includes ESM2-3B fine-tuning; we should use available inference weights rather than retraining a 3B model for this experiment.

Ligand-conditioned complex prediction belongs to a separate known-ligand track. Giving a competing method the reference ligand or bound structure changes the question. BioEmu alone is a conformation generator, so its relevant control includes a pocket detector and ranker.

The CryptoBench authors report AUPRC 0.43 for pLM-NN versus 0.19 for PocketMiner on their shared CB-PM subset. Their CB-full pLM-NN result is 0.36. These are published context, not Ember results or values to mix into a new leaderboard. Official protocol reproduction and our custom end-to-end evaluation must be separate tables.

## Build the model in three steps

### A. Frozen sequence features and a small head

Cache per-residue ESM-2 embeddings once. Use the published backbone for official baseline reproduction. For Ember's affordable experiment, start with the previously proposed 150M backbone; choose a larger frozen backbone only after profiling. Backbone differences must be disclosed.

Train a two-hidden-layer residue MLP, initially 256 then 128 units, with dropout and a binary output. Add a regularized linear probe. Start with masked binary cross-entropy, protein-balanced sampling and development-only early stopping. Class weighting is fitted from training data, not test labels. Report the exact trainable parameter count.

Map residue predictions to sites using a fixed spatial/surface adapter tuned on development data. Do not let one whole-protein cluster earn an easy hit: report predicted site sizes and use an overlap metric that penalizes oversized predictions. Unannotated residues are benchmark nonmatches with unknown biological binding status.

### B. Add inexpensive structural and ensemble features

Compute apo pocket shape/exposure/contact descriptors. First train a small regularized or boosted-tree site ranker. Only then compare the proposed static geometric graph encoder.

For a development smoke test, cache 16 BioEmu conformers for a small metadata-selected sample. Profile total cost, including embeddings, reconstruction, CPU cavity detection, storage and failures. BioEmu is frozen and sequence-conditioned; the experimental apo supplies structural input to the ranker.

Validate geometry and residue mapping, align frames before coordinate-based grouping, detect pockets, and deduplicate observations into sites. Add variation in exposure, contacts and cavity geometry to the static ranker. Include mean/max statistics before attention pooling. Treat conformers as an unordered set, never as consecutive MD frames. Detection frequency summarizes support across sampled conformers.

Do not automatically discard rare openings. Candidate coverage should be measured before ranking. Sequence-derived surface proposals can be a development ablation for sites absent from cavity proposals; reference ligands cannot generate proposals.

### C. Learn the ensemble correction only when justified

The candidate architecture is a shared geometric graph encoder applied to each conformer, followed by permutation-invariant pooling and a residual correction to the sequence/apo score. A compact GVP model from the prior plan is one candidate for development comparison.

Train residue membership plus within-protein site ranking, with a small, predefined tuning budget. With incomplete site annotations, ranking targets mean better recovery of known sites, not universal binding preference. Defer the conformer-geometry head until localization works and its supervision has been audited.

Use this ablation ladder: sequence only; sequence+apo; sequence+apo+simple ensemble statistics; sequence+apo+learned ensemble pooling. Keep the same embedding backbone and, where applicable, candidates. If simple statistics match the graph network, retain the simpler model. If all ensemble variants fail to improve development performance, report that result and retain the stronger simple baseline.

## Evaluation contract

Run two tables: official-protocol reproductions, and a common-input end-to-end comparison. The latter uses the custom common-input benchmark protocol defined here.

Primary metric: macro per-protein annotated-site recall at three unique predictions. For each protein, match predicted and annotated residue sets one-to-one with Jaccard >=0.25, divide recovered annotated sites by annotated sites, and average across proteins. This threshold is provisional until development sensitivity checks and protocol freeze. Fix tie handling and matching algorithm in code.

Secondary metrics: recall@1 and @5; residue average precision with its exact implementation specified; candidate coverage at a fixed pool cap; fraction of covered sites recovered in the shortlist; output success rate; predicted site size; latency and total dollars per target. Report macro residue AP and any official pooled metric separately. Undefined residue metrics require a prespecified policy and reported counts.

Use an identical cached candidate pool for ranking-only comparisons between compatible scorers. Use each method's own proposals for end-to-end comparisons. Candidate coverage bounds the ranker’s attainable recall. Methods producing only residues get an explicit, development-fixed adapter; preserve their native evaluation too.

If reporting coordinate metrics, distinguish center-to-center distance from center-to-any-ligand-atom distance and give the cutoff. Align reference and prediction coordinates explicitly. Never combine an overlap or distance criterion after seeing which yields the higher test score.

For conformational diagnostics, evaluate local mapped-pocket geometry against held-out bound structures under a predefined alignment. Report best-of-fixed-N sampling coverage separately from the geometry of the model-selected conformer. Best-of-N is an evaluator-only oracle diagnostic using reference information. Docking readiness requires a separate geometry assessment.

Freeze the eligible cohort before model outputs. Failed jobs are misses for the primary site metric; publish failure reasons and compute consumed. Paired successful-only results may be supplemental. If reference data are invalid, exclusions must be resolved before freeze or disclosed as a protocol amendment.

Report paired differences with protein/family-cluster bootstrap intervals, using the same targets for both methods. Conformers and related structures are not independent samples. Small subsets can support a feasibility finding while lacking power for a superiority claim.

## How to analyze and improve Ember

| Observed failure | Likely next experiment on development data |
| --- | --- |
| Correct site absent from candidates | Improve proposals, sampling or reconstruction; measure candidate coverage before training a larger ranker. |
| Correct candidate exists but ranks below three | Improve ranking labels/features; compare simple and learned ensemble pooling. |
| Sequence-only matches ensemble model | Inspect ensemble validity and whether geometry supplies additional information; simplify if it does not. |
| Site localized, selected geometry stays closed | Improve representative-conformer selection or sampling; keep localization and geometry claims separate. |
| Many apparent false positives | Inspect annotations, oversize/merged sites, cofactors and adjacent pockets; do not assume unannotated predictions are biologically false. |
| Gains vanish for remote families | Investigate homology leakage and shortcuts; improve data diversity rather than randomizing more frames. |
| Success-only metrics look strong, overall recall weak | Fix failed mappings, unsupported chains and crashes. |
| Marginal gain consumes much more compute | Reduce sample count using development data, test simple statistics, or defer expensive inference to uncertain cases in a later version. |

After freezing and opening test results, descriptive analysis is allowed. Test-directed model changes create a new version and require a new untouched holdout for a fresh claim. Do not use CryptoBank external results to select architecture and still call it an independent final test.

## Budget and implementation order

The $200 figure is a proposed cap for a staged feasibility experiment; the feasible comparator and protein counts depend on measured costs. Keep the existing provisional allocations: $25 smoke profiling, $65 feature generation, $50 training, $35 final evaluation, $25 contingency. These include all attributable cloud charges; cap checks must be implemented in the runner. Actual provider rates and throughput need measurement before launch.

1. Acquire original releases; hash files; produce the train/development/test manifests and overlap report. Resolve licenses for data and checkpoints before their intended use.
2. Implement one output schema, mapping/alignment checks, top-k deduplication and reference-hidden inference. Repair the current legacy evaluator before reusing it.
3. On training/development examples, reproduce the cheap baseline and run 5–10 diverse smoke targets through external adapters. This stage checks schema, runtime and failure behavior; predictive evaluation follows the protocol freeze.
4. Cache embeddings and fit the sequence MLP plus simple ranker. Reserve evaluation funds before any ensemble generation.
5. Profile and add conformers only if the projected full selected cohort fits. If it does not, choose a deterministic metadata-based subset before viewing test labels or predictions and name the subset honestly.
6. Freeze checkpoint, versions, candidate budget, thresholds, adapters and cohort. Evaluate Ember and feasible comparators on identical targets. Clearly mark unavailable methods as not run.
7. Produce a results table, per-target records, paired confidence intervals, cost curve, error gallery and supported claim. Preserve raw outputs to enable later review.

Existing code has concrete blockers: `dynamics/datasets.py` computes a ligand centroid from all matching residue names rather than a selected ligand instance; `aggregate.py` lacks an explicit shared coordinate transform; `benchmark.py` awards a hit for any candidate rather than a capped ranked shortlist; `cryptic.py` imposes a 20% persistence cutoff. Fix and test these scientific contracts before using the pipeline's numbers externally. Current unit tests cover legacy behavior; the scientific comparison requires the corrected contracts.

The minimum useful result is a reproducible, nonleaking baseline and an honest answer about whether conformational evidence improves shortlist quality. A stronger fundraising result would show a paired accuracy or cost advantage, supported on an independent cohort, with inspectable examples and a concrete prospective validation proposal. Both remain evaluation goals for the untrained model.

## Required result artifacts

- `dataset_manifest`: exact release hashes, partitions, mapping and exclusions.
- `method_manifest`: code/checkpoint hashes, training exposure, inputs and settings.
- `predictions`: target, method, unique site rank, residue IDs, representative conformer and status.
- `per_target_metrics`: site hits, residue metrics, candidate coverage, geometry, runtime, cost and failure reason.
- `leaderboard`: common cohort ID and size, primary/secondary metrics, paired uncertainty and measured cost.
- `analysis`: ablations, predeclared subgroup results, representative successes/failures and limits.

These are implementation requirements. Dataset acquisition, executable adapters, training and benchmark evaluation follow in the implementation stage.
