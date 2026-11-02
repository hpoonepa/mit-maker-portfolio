# Ember implementation ledger

Started 2026-09-28, approximately 15:26 America/New_York.

## Authorized scope

The user confirmed Ember Pocket after requesting roughly three hours of research,
planning and implementation. No model training, model inference, GPU jobs, paid
compute, cloud provisioning or biological benchmark runs are authorized now.
Small local software-contract checks are distinct from testing a trained model.

## Evidence recovered

- The September 23/24 chat established the dynamics pivot, a proposed USD 200
  experiment and the need for a meaningful comparison with public alternatives.
- `docs/ember-pocket-master-build-plan-2026-09-24.md` supersedes the earlier GVP
  default: frozen ESM-2 features, R0 residue head, S0 static ranker, E0 residual.
- `docs/ember-pocket-benchmark-protocol-2026-09-24.md` specifies CryptoBench,
  optional CryptoBank external validation and a one-to-one top-three site metric.
- The original `dynamics/` pipeline has scientific-contract defects documented in
  that plan. It remains isolated; new code must not silently inherit them.
- The workspace root is not a Git repository. Preserve unrelated work and provide
  a file/hash inventory rather than claiming a commit exists.

## Work sequence

1. Verify primary sources, inspect upstream schemas and pin relevant source files.
2. Build manifests, residue mapping, grouping and evaluation with local fixtures.
3. Implement immutable feature caching, feature extraction and compact models.
4. Implement cached-data training/inference interfaces, provenance and safeguards.
5. Prepare split audit, compute budget, staged test protocol and commands.
6. Review scientific contracts, run only non-model checks and record limitations.

## Decisions

- No fresh foundation-model training or GVP is included in v0.
- Conformations are unordered evidence. Detection frequency summarizes support across sampled conformers.
- Primary site evaluation uses residue sets and maximum-cardinality matching;
  geometry is a separately reported diagnostic.
- Test annotations are separate from inference records and feature caches.
- No provider-specific launcher is needed before provider choice and authorization.
- Read-only acquisition of small public source/metadata files is allowed. Large
  releases, model weights and full dataset processing remain a later stage.

## Progress

- Recovered the recent chat and controlling September 24 documents; user confirmed
  Ember Pocket. Created an isolated package under `dynamics/ember`.
- Audited primary repositories and real output formats. Saved commit/file hashes,
  source licenses, original release inventory and training annotation checksums.
- Confirmed 885 training and 222 test apo IDs in original split metadata. Downloaded
  training annotations only; no test annotation file, model weight, trajectory or
  original 1.15 GB coordinate archive was acquired.
- Built explicit residue/ligand mapping, quality screens, complete-link candidate
  grouping, masked features, immutable caches and separate input/reference types.
- Authored R0/S0/E0, bounded training, inference, cross-fitting, release provenance
  and checkpoint recovery. Tensor-framework execution remains deferred.
- Added native fpocket/P2Rank/Lacuna output adapters, a cached R0-mean baseline,
  failure-inclusive matching/evaluation and a budget reservation ledger.
- Checked synthetic contracts and public parser fixtures, including author-label
  joins for three hash-selected training structures. Synthetic scores exercise software
  contracts; biological performance evaluation remains pending.
- Added starting configurations, an extensive staged compute/test plan, a
  default-deny experiment plan and checksummed local verification receipts.

## Review findings incorporated

- Treat the BioEmu reconstructed PDB as topology/first frame; read its XTC for all
  conformers, with explicit output paths and angstrom/nanometer handling.
- Use real one-based fpocket filenames and actual descriptors, not sphere counts
  as residue counts or missing coordinates as an origin-centered pocket.
- Preserve canonical sequence gaps, insertion codes and multi-character chains.
- Use maximum-cardinality site matching; preserve failure denominators and group
  dependence. Keep AP distinct from original trapezoidal PR-AUC.
- Exclude an OOF prediction's group from both fitting and early stopping. Generate
  explicit training/inner-selection/prediction group lists.
- Keep S0 weights and dropout frozen; zero-initialize E0's output and require exact
  static fallback in the deferred model tests.
- Commit checkpoints through one atomic alias, preserve the previous generation,
  and bind preprocessing/group provenance to the checkpoint. Resume the whole
  copied run directory, preserving its best-development checkpoint.
- Reuse the loaded ESM encoder, reuse contact calculations across candidates, and
  compare against CPU NMA and mean-R0 controls before paying for larger designs.
- Record Lacuna’s generator in a separate run receipt and explicitly select NMA
  instead of environment-dependent `auto`.
- Report the top-k output-budget ceiling when a protein has more reference sites
  than output slots. Distinguish original generated-frame prefixes from accepted
  frame prefixes when planning later sample-count comparisons.

## Deliberately unfinished at the compute boundary

No model checks, training, inference, external detector execution, cloud jobs or
paid resource allocations were performed. The full eligible cohort, relatedness
search, source exposure audit, physical thresholds and exact model environments
remain to be established under the staged plan. The model is untrained;
predictive comparison with baselines remains pending. The next meaningful validation
is the small deferred CPU model check, followed by real development-only adapters
and cost profiling. `artifacts/local-verification.json` records the final local
check count and code hashes; `artifacts/preflight.json` lists unresolved gates.

## Handoff status

Final local checks completed around 2026-09-28 20:51 UTC (16:51 America/New_York),
about 85 minutes after the recorded start. Work reached the model-execution
boundary before the approximately three-hour target. The last verification passed 60 tests with zero
failures, errors or skips; syntax inspection, Ruff lint and formatting passed.
Model execution and scientific benchmark checks remain pending.
