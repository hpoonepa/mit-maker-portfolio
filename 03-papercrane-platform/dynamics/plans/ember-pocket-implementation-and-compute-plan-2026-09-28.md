# Ember Pocket: implementation, experiment and testing plan

28 September 2026. Status: pre-compute implementation. The user confirmed the
Ember Pocket project and authorized research, planning and coding, while excluding
model execution and compute runs for this session.

This document operationalizes the [September 24 master plan](ember-pocket-master-build-plan-2026-09-24.md).
The new code is in [dynamics/ember](../src/ember/README.md). No learned weights,
biological model-validation result or cloud spend has been produced by this work.

## 1. The model we should build

Build a compact model that identifies and prioritizes cryptic sites using a
protein's sequence, an explicitly selected apo chain, and a small cached set of
conformations. Its deliverable is three distinct site hypotheses with original
residue identifiers, structural evidence, a representative conformation and
honest failure/provenance information.

The first question is narrow and testable: **does conformational evidence improve
the top-three shortlist beyond a strong sequence-plus-apo model at an acceptable
total cost?** A small positive result on an honest held-out cohort is more useful
than an unvalidated large architecture. It is also possible that S0, or a public
baseline, wins; that outcome should determine the next experiment.

This is an initial step toward modeling functional states. It is not a
time-dependent motion predictor. Later kinetics, state-population or
mutation/ligand-response work needs corresponding time-series, thermodynamic or
intervention data. Pocket labels alone cannot establish those capabilities.

## 2. What the literature changes in our design

| Evidence | Engineering decision | Test of the decision |
| --- | --- | --- |
| [CryptoBench](https://github.com/skrhakv/CryptoBench/) provides training/test resources and a protein-language-model baseline | Start with frozen sequence embeddings and a small residue head | Matched-encoder linear probe versus R0; macro residue AP and site shortlist quality |
| [BioEmu](https://github.com/microsoft/bioemu) supplies sequence-conditioned conformational samples | Reuse a frozen generator; cache real topology+trajectory output | Requested/accepted frame counts, geometry validity, candidate coverage, total cost |
| [PocketMiner](https://www.nature.com/articles/s41467-023-36699-3) learns signals associated with pocket formation | Include meaningful structural/contact evidence, but defer a new GVP until cheaper features justify it | Static versus ensemble correction on the same candidate pool |
| [Lacuna](https://github.com/mooreneural/lacuna) already combines conformations, detectors and learned ranking | Treat it as a direct comparator; the pipeline combination is not sufficient novelty | Named reproducible configuration on the identical cohort and output budget |
| [Seq2Pocket](https://github.com/skrhakv/seq2pocket) maps residue signals to 3D sites | Surface proposals are a controlled follow-up, not a claimed invention | Coverage gained versus added candidates and shortlist competition |

The contribution to seek is measured quality per dollar, plus a clear diagnosis
of where conformational evidence helps. Do not promise universal superiority or
substitute headline numbers from differently filtered published benchmarks.

The closer Lacuna source audit strengthens two controls. Its CPU NMA/alpha/learned
configuration is a required low-cost comparator, and a mean-R0-logit scorer on
the matched candidate pool is a required sequence-only ranking control. Lacuna's
[ranking notes](https://github.com/mooreneural/lacuna/blob/31660b7634b8d2ef473e8082eae0c117cd5aee50/docs/RANKING.md)
report that sequence summaries dominate its linear PLM-assisted ordering. Ember
therefore needs evidence that its extra descriptors help beyond that cheap score.
Its [benchmark notes](https://github.com/mooreneural/lacuna/blob/31660b7634b8d2ef473e8082eae0c117cd5aee50/docs/BENCHMARKS.md)
also disclose repeated test-fold measurement during tool development. Record this
exposure; comparison on the public test is not a claim of a completely blind
prospective experiment.

Specific source corrections were verified in
[the source audit](../src/ember/research/README.md): BioEmu's published paper
is Science 2025; its reconstructed PDB contains one frame and its XTC contains the
ensemble; fpocket filenames are one-based in the pinned output; and the original
CryptoBench PR-AUC implementation differs from non-interpolated average precision.

## 3. Architecture and compute discipline

### R0: frozen sequence features to residue evidence

Use ESM-2 `esm2_t30_150M_UR50D`, last-layer 640-dimensional residue embeddings.
Remove special tokens and assert exactly one row per canonical sequence residue.
Hash sequence, checkpoint, tokenizer, implementation and preprocessing into the
cache identity. Do not update the encoder.

Reuse one `FrozenESM2Encoder` instance while streaming a cohort; do not reload the
foundation model for every sequence. R0 inference checks the embedding key against
the sequence and encoder identity in its trained release.

The head is LayerNorm(640), Linear(640,256), GELU, dropout 0.1,
Linear(256,128), GELU, dropout 0.1, Linear(128,1). Its analytical parameter count
is **198,401**. Measure it again when the deferred model checks run. Compare a
matched 641-parameter linear probe. Different backbone sizes belong in a
full-method comparison, not an architecture-only claim.

Train masked binary cross-entropy, equal weight per protein, training-only
positive weighting capped at 20, learning rate 1e-3, maximum 50 epochs, effective
batch eight proteins and development patience five. The cap is a starting
hyperparameter, not a biological constant. The label means membership in the
benchmark's known annotation; an unannotated residue is not proven nonbinding.

### S0: static shortlist scorer

Use 14 apo/sequence descriptors and 14 missingness indicators. These include R0
logit summaries, site size/chemistry, observed fraction, radius of gyration, local
packing and available apo detector descriptors. Fit imputation/normalization only
on training proteins, with protein-balanced statistics. Suppress numerical effects
from columns that are constant/unobserved during fitting.

Start with a 29-parameter linear scorer. The implemented 64/32 MLP comparison has
3,969 parameters. These are analytical counts. Coupled L2 regularization via Adam
is used for linear heads; MLPs use AdamW. Both defaults use coefficient 1e-4 and
gradient clipping at one. A large model is not needed merely to combine a few
dozen descriptors.

Training-site features must use out-of-fold R0 predictions. A scored group's
labels must be absent from both R0 optimization and early-stopping selection.
For each outer training fold, use a small internal development split drawn only
from the remaining training groups, or freeze an epoch count without consulting
the outer fold. Refit the final R0 on the declared training population for normal
development/test inference. Never substitute in-sample training logits silently.

### E0: learn what the conformations add

Score each site as `frozen_S0(static) + correction(ensemble)`.

The 25 ensemble descriptors include unique-frame support, detector/volume/SASA/
quality statistics, residue overlap with the site medoid, changes from apo and
local contact changes. Missingness adds 25 indicators. Contact matrices are
computed once per frame and reused across sites.

The default linear correction has 51 parameters. A 64/32 MLP correction has 5,377.
Initialize the last correction layer to zero. Freeze S0 weights and keep its
dropout in evaluation mode even while E0 trains. With zero valid frames, return
the exact S0 result and flag a static fallback. Do not invent ensemble evidence.

Use within-protein pairwise logistic loss: known-site overlap ≥0.25 versus overlap
<0.10, with at most 256 deterministic sampled pairs per protein. Ambiguous
intermediate overlaps supply no pair. Proteins without usable pairs remain in
evaluation and residue learning. Candidate-missing targets must not disappear.

The three planned E0 development configurations are linear, small MLP, and the
selected form with explicit sample/support counts removed. That final ablation
also removes those columns' missingness flags; other features can still encode
observation availability, so it is not perfect removal of every frequency proxy.

The foundation models dominate compute. Cache once, train tiny heads repeatedly,
use the same ensembles for attribution comparisons and stop early if the simple
controls win. No GVP, generator fine-tuning, new MD campaign, ligand-conditioned
generation or huge search is included in the first experiment.

## 4. Data: what is known and what remains

The original OSF split metadata, not a paper's retained denominator, identifies
1,107 apo structure IDs: 885 training and 222 test. All four training annotation
files were downloaded and verified against OSF SHA-256 values. They contain 4,393
apo/holo/ligand pair records. These are correlated observations, not 4,393
independent proteins. Test annotations were not downloaded.

The original structure archive is 1,145,203,712 bytes and remains undownloaded.
Three hash-selected training PDBs were acquired from current RCSB solely to check
the mapper. Current PDB downloads are not claimed identical to the archived
benchmark structures. Parser checks succeeded for 7R00/AAA, 8JIS/R and 4OS8/B;
8JIS's 394-residue entity exceeds the provisional 350-residue scope.

The same three fixtures also join successfully to the original training author
annotations: respectively 6, 25 and 18 positive residues, with 1, 1 and 2 custom
reference sites. The recorded annotation mapping audit is a parser check, not a
biological accuracy test or an eligibility determination.

Next data steps, before expensive features:

1. Acquire and verify the original coordinate archive and applicable use terms.
   Preserve raw files; do not replace release coordinates with current PDB files
   without declaring a separate dataset version.
2. Review biological assembly, chain, soluble/folded monomer support, required
   chemistry and the 80–350 length criterion. Store evidence for each decision.
   The number of chains in a crystal asymmetric unit is not monomer status.
3. Map mmCIF entity sequence and `atom_site.label_seq_id` to exact author IDs.
   Missing positions remain masked. Modified polymer chemistry or ambiguous maps
   become explicit pre-freeze failures.
4. Preserve the official test assignment. Build group-aware development from the
   official training population only. Import MMseqs2 similarity edges with
   explicit fractional identity and shorter-sequence coverage; initial audit
   thresholds are 40% and 80%, with structural/domain review where available.
5. Purge training relatives of test/external groups under the declared rule.
   Record edges and exclusions. Exact PDB disjointness and singleton IDs do not
   establish absence of homology.
6. Convert training annotations into separate reference records. Join exact
   author residues and exact ligand instances. Do not truncate multi-chain sites
   into an easier supported chain without documenting the eligibility decision.
7. Multiple ligand/pair observations can describe the same site. The proposed
   custom site benchmark uses complete-link reference grouping at Jaccard 0.75
   and a residue-set medoid. Audit/sensitivity-check this on development data and
   freeze it independently of prediction results. Preserve the official residue
   benchmark in a separate table.
8. Freeze inputs/references/splits with hashes. Foundation-model pretraining
   exposure and comparator training exposure remain separate audit fields.

CryptoBank archive metadata is now accessible; its main ZIP is approximately
152 MB. It has not been downloaded or unpickled. External evaluation is optional
until its experimental-apo slice, labels, use terms and cross-source relatedness
are audited. Do not reuse a model's own training proteins as independent evidence.

## 5. Candidate and structure pipeline

Stage the selected apo chain into a normalized detector PDB while preserving the
canonical-to-author mapping. Run the pinned detector only in the next authorized
stage. Keep raw output and exact residue membership. Missing/corrupt output is a
failure, not a successful empty cavity list or an origin-centered pocket.

For BioEmu, start the pilot with 16 requested conformations. Keep the selected
checkpoint fixed; the current plan names v1.1. The first experiment may use 32
only after end-to-end profiling. Do not increase the quota until enough favorable
samples appear. Requested, generated, filtered, reconstructed and accepted counts
are distinct and must be recorded with seeds and retries.

Reconstruct all atoms and read every XTC frame against its topology. The new
plan explicitly sets the reconstruction output directory. It initially disables
MD equilibration/minimization so those costs and effects cannot be hidden. Compare
the reconstruction-only quality on development examples; if minimization is
needed, pin that protocol and include it consistently in costs and comparisons.

Screen chain continuity, missingness, atom completeness and gross nonlocal
clashes. The implemented screen is deliberately limited: detailed stereochemistry,
bond geometry and energetics still require a real validated tool/protocol before
calling output physically screened for the scientific release. No relaxation
routine establishes equilibrium or binding by itself.

Group mapped observations with deterministic complete-link residue overlap ≥0.35,
use a medoid rather than the unrestricted residue union, and retain rare valid
openings. Count at most one observation per frame. The provisional 64-site cap
uses a reference-free detector score; save the discarded IDs and assess coverage
loss before freeze. Coordinate-distance grouping is allowed only after explicit
alignment to the apo frame.

Choose each supporting conformer by a fixed detector-score rule among accepted
observations. This is a heuristic selector, not a trained conformer head. The
best geometry under the reference is an evaluator-only oracle diagnostic.

## 6. Validation ladder and gates

| Gate | Work | Advancement condition |
| --- | --- | --- |
| A: local software | Schemas, source parsing, residue/ligand mapping, grouping, evaluation, cache, budgets | Contract checks pass; assumptions and errors recorded |
| B: tiny model execution | Loss/gradient tests, exact static fallback, tiny overfit, interrupted/resumed training | All authored CPU model checks pass before biological training |
| C: external adapters | A few development-only systems through embeddings, detectors, sampler and reconstruction | Actual files/frames match pinned interfaces; chemistry/units verified |
| D: static floor | Linear probe, R0, native fpocket/P2Rank, grouped cross-fitting, S0 | Valid development metrics, correct labels, useful candidate coverage, measured cost |
| E: ensembles | Length-stratified 16-frame pilot, quality checks and identical cached proposals | Coverage/validity justify generation cost; complete experiment fits remaining cap |
| F: correction | At most three E0 configurations; selected-seed repeats only if affordable | Prespecified development advantage or useful quality/cost tradeoff |
| G: frozen public test | Freeze code, weights, data, preprocessing, thresholds, baseline configurations | One release evaluation; every eligible failure retained |
| H: external/prospective | Nonoverlapping external subset and later blinded partner experiment | Appropriate independence and separately authorized experimental resources |

Only Gate A was executed during this session. Code for Gate B and later stages
is not evidence those stages have passed.

The deferred CPU check entry point is:

```bash
python -m dynamics.ember.model_checks.run_checks --execute-model
```

This command is intentionally **not run yet**. In a newly authorized session,
resolve a dedicated model environment first. `requirements-model.in` is an input
specification, not a validated lock. Keep BioEmu/HPacker isolated from the small
head environment. Freeze installed versions and save checkpoint hashes.

Model checks include loss masking, ranking-gradient direction, frozen S0 dropout,
zero-initialized correction, exact no-ensemble fallback, candidate-order
equivariance, tiny synthetic R0 overfit and CPU checkpoint-resume equality. Run
the actual ESM tokenizer/embedding adapter and BioEmu topology/XTC extraction on
real development inputs only after these checks pass.

## 7. Benchmark and comparisons

Primary metric: macro per-protein annotated-site recall@3. A prediction matches a
reference at residue Jaccard ≥0.25. Use maximum-cardinality one-to-one matching,
deterministic ties and final prediction deduplication at Jaccard ≥0.5. Larger
residue sets incur a Jaccard penalty; also report site-size distributions.

Two mandatory result tables answer different questions:

- **Native end to end:** each method receives the same allowed apo/sequence input
  and produces its own proposals. Start with fpocket, P2Rank and Ember static;
  include Lacuna's CPU NMA/alpha/learned pipeline and Ember ensemble track. Add
  other public methods as the measured budget permits.
- **Matched candidate pool:** reuse the exact accepted conformations and grouped
  sites for ordinary detector scoring, mean R0 logit, frozen S0 and S0+E0. This isolates ranking
  from improved proposals. Static scoring of this pool still benefits from
  ensemble-generated candidates and must be labeled accordingly.

Record author-version configurations for CryptoBench pLM-NN, PocketMiner/
AE-PocketMiner, Seq2Pocket and Lacuna. Adapters/weights not reproduced remain
"not run"; do not fill missing rows with literature scores. Different input
conditioning, checkpoint backbones or eligibility subsets need separate labels.

Secondary results: recall@1/@5, candidate coverage before/after cap, shortlist
conversion conditional on coverage, macro residue AP, physical-output rates,
native failure/fallback counts, selected-conformer local geometry, oracle
best-of-fixed-N geometry, cold/warm runtime and total measured cost.

All eligible failed/missing predictions are misses. Invalid references are
pre-freeze errors rather than post-result exclusions. Zero-site controls have a
separate summary; recall is undefined for them. A forced top-three ranker does
not provide a calibrated target-level negative/abstention decision. Report this
limitation rather than claiming diagnostic specificity.

Use paired family-cluster bootstrap intervals with 10,000 resamples on the
identical cohort/protocol/reference hashes. The estimand is macro-protein recall;
the resampling unit is the dependence group. Report seeds individually. These
intervals do not account for all model-selection or annotation uncertainty.

An aspirational +10-point development improvement is not a forecast. A positive
point estimate with a broad interval is inconclusive. If development evidence is
weak, inspect coverage, mapping and quality before buying more sampling. Keep the
best simple method if the ensemble correction adds no useful information.

## 8. Compute plan and stop rules

The existing USD 200 amount is a proposed **all-in ceiling**, not authorization
and not a verified price quote. No paid jobs were launched. Preserve the allocation:

| Stage | Maximum proposed USD |
| --- | ---: |
| Model/tool smoke and end-to-end profiling | 25 |
| Cached embeddings/conformations | 65 |
| Training and development | 50 |
| Frozen final evaluation | 35 |
| Storage, failed attempts and late billing reserve | 25 |
| Total | 200 |

Measure short/medium/long supported development systems. Include cold setup,
weights, MSA retrieval, ESM features, BioEmu sampling, reconstruction, physical
checks, pocket detection, feature extraction, training, CPU/storage/transfer and
failed attempts. A sampler-only timing table cannot price the pipeline.

`budget.project_cost` requires measured end-to-end profiles and an explicit
hourly rate. It uses the slowest measured example per length stratum, a default
1.5 failure allowance and separately supplied fixed costs. Treat that as an
initial conservative projection, not a guaranteed upper bound. Add provider
startup/billing granularity and actual resource receipts before committing.

Reserve a job's conservative maximum before launch; reconcile actual spend even
when it exceeds the reservation. The ledger preserves final-evaluation money
and blocks new reservations after a stage breach. It does not stop a cloud bill.
Provider-specific wall-time limits, idle termination, bounded retries, durable
storage and shutdown verification still need implementation once the provider is
chosen. No generic SDK launcher was added to this build.

When cost is too high, reduce optional comparators/sweeps first. Then select a
smaller fixed sample count on development data. If necessary, use a metadata-
selected family subset chosen before prediction results and name that restricted
cohort explicitly. Do not shrink a test denominator after failures. Do not consume
the final-evaluation reserve chasing development gains.

### What a small sample budget can miss

Even perfect ranking cannot recover an unproposed site. For intuition only, if
each independent draw has probability `p` of producing a valid, detectable site,
the chance of seeing it at least once in `N` draws is `1 - (1 - p)^N`:

| Hypothetical per-draw detectability | 16 draws | 32 draws |
| --- | ---: | ---: |
| 1% | 14.9% | 27.5% |
| 5% | 56.0% | 80.6% |
| 10% | 81.5% | 96.6% |

These are analytical illustrations, not measured BioEmu probabilities, physical
occupancies or guarantees of independent samples. They explain why retaining a
rare accepted observation matters and why a low sample count cannot promise
exhaustive cryptic-site discovery. The residue model can rank an existing
candidate but cannot create a missing one. Diagnose low coverage before spending
on a more elaborate ranker; only then consider a prespecified proposal change.

For a later sample-count curve, take fixed prefixes by original generated-frame
identity from one cached run, before quality selection. Taking the first 16
*accepted* frames from 32 requested draws is not a 16-requested-draw experiment.
Preserve raw batches and the filter index map; upstream filtered XTC row numbers
alone do not establish that original identity. No sample-count curve was run here.

Also report the output-budget ceiling: with four distinct reference sites, three
predictions can recover at most 75%. The evaluator now records this ceiling per
protein and its macro average. Candidate and duplicate-site constraints can lower
it further. Do not interpret all shortfall from 100% as a ranking defect.

Portable training checkpoints include model, optimizer, epoch/cursor, sampler
position, Python/Torch random states, config, feature/label signature, split/code
hashes, environment versions and best-development history. Mixed precision and
scheduler are currently disabled and explicitly recorded as absent. Resume on
the same environment/device for exact replay; cross-hardware equality is not
promised. Carry the whole run directory and checksums between authorized sessions.
Checkpoint aliases are relative Unix symlinks to checksummed immutable blobs;
copy the directory with symlinks preserved. One atomic alias replacement commits
the new data/hash together, and the current plus previous generation are retained.
Use one training worker per run directory. Normalizers, encoder identity and
training/selection groups are bound into the checkpoint's release signature.
The old discussion of seven credit balances does not establish that their terms
permit pooling, or authorize use of any account.

## 9. Commands and artifacts for the next operator

Use the existing local environment for inspection only:

```bash
run/.venv/bin/python -m unittest discover -s dynamics/ember/tests -t . -v
python3 -m dynamics.ember plan --output dynamics/ember/artifacts/experiment-plan.json
python3 -m dynamics.ember preflight dynamics/ember/artifacts/experiment-plan.json
```

Preflight is expected to return a blocked/full-experiment-not-ready status today.
That is the correct result of respecting the no-compute boundary. It requires
named, checksummed evidence receipts in addition to readiness flags.

After separately authorizing the applicable compute stage, use the CLI's
`train-residue`, `train-sites` and `predict` commands with explicit cached
manifest paths. Their help output lists the required inputs. Each defaults to
refusing model execution; they do not create cloud resources. The supplied JSON
training configurations are starting settings, not tuned results.

Store these final experiment artifacts:

1. Original release/checkpoint checksums and use-term/exposure inventory.
2. Reviewed eligibility, canonical residue maps, relatedness edges/groups, split
   manifests and out-of-fold lineage.
3. Raw/accepted frame manifests, detector output, uncapped/capped sites and cache
   keys, including failed jobs and retry counts.
4. Training history, latest and best checkpoints, normalizers, frozen model
   release and environment lock.
5. Predictions, every per-target metric, paired comparisons, cost receipts,
   failure examples and all relevant ablations.
6. A restricted, source-supported scientific claim and an experiment proposal
   for blinded validation of selected sites. No invented benchmark numbers.

## 10. Remaining limitations before a real result

The local implementation is substantial but not a trained/validated product.
Torch/model execution, embedding extraction, trajectory IO with installed
MDtraj, actual detector binaries, sidechain reconstruction, checkpoint-resume
parity and end-to-end throughput remain untested here. The complete eligible
cohort, relatedness audit, foundation-model exposure, quality thresholds,
reference-site merging and exact environment locks remain unfrozen.
The Lacuna parser was checked against a saved upstream report, but its executable
was not run. Pin `--backend nma --detector alpha --rank-by learned`; backend `auto`
can select a different generator depending on installed extras. Its native JSON
does not attest to that configuration, so save an independent command/environment
receipt. `n_conformers` includes the apo input, and `n_pockets_found` counts the
reported list after output truncation. Do not infer total proposal coverage from
a truncated report. The CLI has no seed option in the pinned version; the adapter
smoke must establish repeatability or use a documented seeded author API wrapper.

Surface proposals, learned geometric encoders, a learned conformer selector,
full stereochemical validation and automatic provider orchestration are deferred.
These are explicit gates or later hypotheses, not hidden successful steps.

The immediate next decision is whether to authorize the small CPU model/tool
smoke stage after reviewing this implementation. There is no need to authorize a
full training campaign until that stage provides compatibility and cost evidence.
