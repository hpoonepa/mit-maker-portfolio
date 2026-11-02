# Research selector development gates

## Objective

Produce a computational selector whose advantage is measurable on unseen
campaigns: useful shortlist recovery, reliable identification of unsupported
comparisons, and eventually lower computational assessment cost. No particular
architecture or LLM receives a privileged role without evidence.

## Implemented foundation

- Versioned supplied-score contract, attribution, and explicit missingness.
- Comparisons within a common evidence cohort, with exact ties preserved.
- Descriptive rank envelopes, source coverage, and method-agreement diagnostics.
- Portable audit report with reproducibility hashes.
- Fixed-budget outcome evaluation, strict unknown labels, paired group summaries,
  and seeded bootstrap intervals without automatic superiority claims.

These components provide software infrastructure. Predictive performance,
uncertainty calibration, binding improvement and research novelty remain evaluation goals.

## Gate 1: A dataset and experiment ledger worth trusting

Version source snapshots, label definitions, assay/measurement endpoints,
candidate identity, target/group identity, upstream selection rules, generator
identity, and predictor settings. Keep unmeasured outcomes separate from
measured negatives. Audit exact duplicates and related target/scaffold groups.

Export the existing model predictions with artifact hashes and complete
normalization metadata. Preserve existing work as a historical baseline rather
than changing its scorer while measuring it. Research and application inference
must agree on golden fixtures before attributing research results to the app.

Treat all previously inspected campaigns as development data. Define separate
training, model-selection, calibration, and final evaluation roles. Every
label-derived prior, feature summary, normalization fit, and prompt feedback
must respect the entire exclusion boundary. File hashes record identity. A dated experiment ledger must also record
when the protocol was frozen relative to label inspection.

Exit: an independently reproducible benchmark export and reviewed split ledger.

## Gate 2: Establish the strongest small model

Compare the strongest available individual score, simple rank aggregation, a
regularized supervised combination, and the existing LLM policy on matched
evidence. Select hyperparameters only within development groups. Evaluate
fixed shortlist sizes and source/target generalization, and report failures.

Measure whether complementary information exists before increasing complexity.
A source-only or missingness-only control can reveal dataset shortcuts. Test
whether the winner persists under source and predictor-version changes.

Exit: a reproducible development comparison that identifies a baseline and its
actual failure modes. A null result is acceptable and prevents wasted scaling.

## Gate 3: Evaluate target conditioning and uncertainty separately

Test a small model that shares statistical strength across campaigns and allows
limited context-dependent adjustments. Compare it against the same architecture
without target context. Target names alone are not an explanation of transfer.

Separately evaluate uncertainty about rankings on held-out outcomes. Agreement,
input completeness, resampling variation, and calibrated uncertainty remain
distinct outputs. Evaluate abstention at matched coverage; do not manufacture
an apparent accuracy gain by declining more cases than the comparator.

Exit: conditional modeling or uncertainty must improve a prespecified endpoint
beyond a simpler control. Drop components that do not earn their complexity.

## Gate 4: Give the LLM a falsifiable role

Compare empirical evidence alone, retrieved literature alone, and their
combination; include anonymized-context and no-LLM controls. Record retrieval
dates, source identity, prompts, model versions, and generated policies.

Keep an LLM contribution in numerical ranking only if it adds held-out value.
Explanations must distinguish evidence from interpretation. An LLM can remain
a useful interface even if it adds no ranking accuracy.

Exit: evidence for a distinct LLM contribution, or a simpler model with an
optional explanation layer. Research novelty requires evidence for a specific contribution.

## Gate 5: Test computational efficiency

Use offline replay with existing complete assessments, measured runtimes, and
hidden evidence. Compare any adaptive assessment policy to all-assessments,
fixed-order, cheapest-first, random, and simple disagreement-based controls.
Keep decision inputs separate from unrevealed values and labels.

Choose a primary quality endpoint and tolerable quality loss before final
evaluation. Compare cost at that matched quality, not an arbitrary blended score.
Validate replay assumptions before extrapolating to real execution costs.

Exit: demonstrated improvement in the quality–cost trade-off, or ship the
strongest simpler scheduling policy.

## Release gate

Release the actual winning model artifact, exact inference transforms, a Python
API/CLI, an application adapter, data manifests, evaluation scripts, documented
limitations, and portable researcher reports. The app must reproduce the model
used in the final evaluation. Publish negative ablations alongside positive ones.

Primary impact is reproducible researcher utility. A paper-level novelty claim
requires a current comparison with prior work and evidence for the specific new
contribution.
