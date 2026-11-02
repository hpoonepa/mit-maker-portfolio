# SENBA: completed frozen-checkpoint evaluation

4 September 2026. All scheduled GPU inference jobs finished successfully.

## Bottom line

The released SENBA checkpoint shows small, consistent endpoint-error gains on
this eight-protein reused validation panel. The gain persists at K=16, and the
exploratory statistical energy score also favors SENBA at K=8 and K=16. However,
the endpoint gain is 42.4% smaller at K=16 than at K=4, and both aligned-C-alpha
spread summaries decrease. The defensible conclusion is a limited, sampling-aware
validation result, not a broad improvement in physical protein dynamics.

The missing training files are not needed to report these completed experiments.
They are needed for additional trained seeds and training-control experiments.
These results can strengthen the existing paper, but do not establish novelty by
themselves or justify a prediction of conference acceptance.

## What actually ran

- Eight fixed mdCATH validation domains; all five 450 K replicas per domain;
  four starts per replica; targets 50 saved frames later in the same replica.
- 160 physical transition pairs; one released SENBA training seed, compared with
  its pinned MarS-FM source checkpoint; ten ODE steps per generated draw.
- Initial K=4 on eight H100 jobs, including the pilot. The seven expansion
  proteins ran concurrently after the technical pilot succeeded.
- Three additional K=4 blocks per transition on eight concurrent H100 jobs.
  The resulting nested K=4/8/16 ensembles preserve the original four draws.
- 640 paired K=4 block records, containing 5,120 generated endpoint structures
  across the two models. This is still only 160 physical transition pairs and
  eight protein-level analysis units, not 640 independent biological replicates.
- Raw and aligned C-alpha arrays, checkpoint/input hashes, frame metadata,
  paired RNG receipts, completion receipts, and derived-prefix provenance saved.

No checkpoint was trained or changed. No independent test-set evaluation was run.

## Results

Positive gains below mean source error minus SENBA error. Each protein is weighted
equally after averaging its 20 transitions. Brackets are conditional 95% percentile
protein-resampling intervals using 2,000 resamples, not general population or
training-seed confidence statements. K=4 remains the prespecified primary workload;
K=8 and K=16 are dependent sampling-sensitivity checks, not new replications.

| Draws per model | Endpoint RMSD gain (angstrom) | Proteins with lower endpoint error | Statistical energy-score gain (angstrom) | Proteins with lower energy score |
| --- | ---: | ---: | ---: | ---: |
| K=4 | 0.02401 [0.01870, 0.02882] | 8/8 | 0.00328 [-0.00115, 0.00767] | 5/8 |
| K=8 | 0.01887 [0.01545, 0.02257] | 8/8 | 0.00604 [0.00359, 0.00841] | 8/8 |
| K=16 | 0.01383 [0.00733, 0.02194] | 8/8 | 0.00642 [0.00160, 0.01166] | 7/8 |

At K=16, mean endpoint RMSD is 10.04244 angstrom for the source and 10.02861
angstrom for SENBA: a 0.138% reduction. Mean individual-sample RMSD decreases by
0.06293 angstrom. Statistical energy score is 6.84525 versus 6.83883 angstrom.
The one domain with worse K=16 energy score, `2k4qA00`, is retained in every summary.

The endpoint gain decreases from 0.02401 to 0.01383 angstrom as K increases from
4 to 16. The post-hoc paired cross-K difference in candidate-minus-source deltas
is +0.01018 angstrom, with conditional protein-resampling interval
[+0.00272, +0.01763]. This quantifies sensitivity in this nested draw realization;
it does not establish the mechanism causing that change.

The finite-K-corrected population-mean MSE diagnostic at K=16 changes by -0.22590
square angstrom, with conditional interval [-0.46080, -0.03177]. Under iid model
draws, this removes model Monte Carlo variance when estimating squared error of
the model mean against one observed target. It does not remove target uncertainty
or measure biological bias or true conditional-mean calibration.

## Interpretation and paper framing

A suitable finding is: **small endpoint gains survive a larger-ensemble check,
but endpoint improvements are ensemble-size-sensitive and should be evaluated
alongside distribution-sensitive scores and spread.**

This is stronger evidence than an endpoint-only table. The favorable larger-K
energy-score differences mean the result should not simply be dismissed as an
endpoint-MSE artifact. They still do not establish calibrated ensembles, retained
biological diversity, source-distribution preservation, or realistic kinetics.

Candidate ensemble variance and pairwise RMSD are lower on all eight domains.
At K=16 their macro changes are -1.87020 square angstrom and -0.11302 angstrom.
Neither direction is intrinsically favorable: narrower ensembles can improve
some endpoint scores without recovering the correct underlying distribution.

All metrics are in individually start-Kabsch-aligned C-alpha coordinate space.
They omit global pose and do not measure all-atom structural accuracy. The energy
score is a statistical forecast score, not molecular energy or free energy. Its
distributional interpretation is limited to the transformed representation.

Important limitations: eight previously used validation proteins, one training
seed, fixed temperature and lag, one set of nested draws, a new evaluator rather
than the unavailable original evaluator, no ordinary conservative-training
comparator, and no untouched experimental-data or test-set benchmark.

## Suggested manuscript addition

We re-evaluated the released SENBA checkpoint against its pinned MarS-FM source
using a new frozen evaluator on eight previously used mdCATH validation domains
(160 same-replica lag-50 transitions). With K=4 paired draws, equal-domain mean
centroid endpoint RMSD decreased by 0.0240 angstrom (0.217%), with lower error on
all eight domains. A prefix-preserving extension to K=16 retained lower endpoint
error on all domains but reduced the mean gain to 0.0138 angstrom (0.138%;
conditional protein-resampling interval 0.0073–0.0219 angstrom). The exploratory
statistical energy-score gain at K=16 was 0.0064 angstrom (interval
0.0016–0.0117), while both aligned-C-alpha spread summaries decreased. These
results support small conditional validation-panel gains that depend on ensemble
size; they do not establish physical kinetics, calibration, independent-test
generalization, or robustness across training seeds.

## Original four-stage roadmap

| Stage | Actual status |
| --- | --- |
| G1: endpoint, decomposition, spread and energy analysis | Completed on this limited eight-protein frozen-checkpoint panel |
| G2: additional training seeds | Not run; other seed checkpoints unavailable |
| G3: sampling check and conservative-training comparator | K=4/8/16 sampling component completed; training comparator not run |
| G4: alpha/retention frontier | Not run; original adaptation/retention assets unavailable |

The earlier G0 summary-receipt audit and technical pilot are complete in their
limited scope; exact reconstruction of the original evaluator remains unresolved.
The missing original assets are not being replaced by invented training results.

## Compute and artifacts

The provider-reported charges at the saved snapshots total **$4.56762390**:
$1.23086024 for the initial panel and $3.33676366 for the extension. All sixteen
apps were confirmed stopped with zero tasks. A $2 late-billing allowance remains
held locally, and the $10 planning reserve remains untouched. These are reported
charges, not a final invoice or a verified account credit balance.

- [Frozen protocol and sampling amendment](FROZEN_EVALUATION_PROTOCOL.md)
- [K=4 report](../reports/sampling-k4-v1/results.md)
- [K=8 report](../reports/sampling-k8-v1/results.md)
- [K=16 report](../reports/sampling-k16-v1/results.md)
- K=16 per-protein plot (submitted separately)
- [Independent K=4 audit](K4_AUDIT.md)
- [Sampling integrity audit](SAMPLING_AUDIT.md)

Operational receipts are preserved privately; the scientific reports above remain included.
