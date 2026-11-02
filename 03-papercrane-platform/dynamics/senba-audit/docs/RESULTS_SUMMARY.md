# SENBA: completed frozen-checkpoint evaluation

4 September 2026. All scheduled GPU inference jobs finished successfully.

## Bottom line

The released SENBA checkpoint shows small, consistent endpoint-error gains on
this eight-protein reused validation panel. The gain persists at K=16, and the
exploratory statistical energy score also favors SENBA at K=8 and K=16. However,
the endpoint gain is 42.4% smaller at K=16 than at K=4, and both aligned-C-alpha
spread summaries decrease. The result measures endpoint error, statistical forecast score and spread
on this reused validation panel, with sensitivity to ensemble size.

The completed experiments use the released checkpoint and saved evaluation
records. Additional trained seeds and training-control experiments require the
missing original training files.

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
  across the two models. The 640 records are grouped into 160 physical transition pairs and
  eight protein-level analysis units.
- Raw and aligned C-alpha arrays, checkpoint/input hashes, frame metadata,
  paired RNG receipts, completion receipts, and derived-prefix provenance saved.

This evaluation uses frozen checkpoints and previously used validation data.

## Results

Positive gains below mean source error minus SENBA error. Each protein is weighted
equally after averaging its 20 transitions. Brackets are conditional 95% percentile
protein-resampling intervals using 2,000 resamples with the training seed and
validation panel fixed. K=4 remains the prespecified primary workload;
K=8 and K=16 are dependent sampling-sensitivity checks using nested draws.

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
the mechanism causing that change remains unresolved.

The finite-K-corrected population-mean MSE diagnostic at K=16 changes by -0.22590
square angstrom, with conditional interval [-0.46080, -0.03177]. Under iid model
draws, this removes model Monte Carlo variance when estimating squared error of
the model mean against one observed target. Uncertainty in the single observed target remains in this diagnostic;
biological bias and conditional-mean calibration require repeated-target analysis.

## Interpretation and paper framing

A suitable finding is: **small endpoint gains survive a larger-ensemble check,
but endpoint improvements are ensemble-size-sensitive and should be evaluated
alongside distribution-sensitive scores and spread.**

The larger-K energy-score differences complement the endpoint-error result.
Together with the spread measurements, they describe forecast behavior in the
aligned coordinate representation. Ensemble calibration, biological diversity,
source-distribution preservation and kinetics require separate assessments.

Candidate ensemble variance and pairwise RMSD are lower on all eight domains.
At K=16 their macro changes are -1.87020 square angstrom and -0.11302 angstrom.
Narrower ensembles can improve some endpoint scores. Their agreement with the
underlying biological distribution requires a separate distribution assessment.

All metrics are in individually start-Kabsch-aligned C-alpha coordinate space.
Global pose is removed by alignment. The energy score is a statistical forecast
score in this transformed representation. All-atom accuracy, molecular energy
and free energy require separate measurements.

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
results measure small conditional validation-panel gains that depend on ensemble
size, for the available training seed at the fixed temperature and lag. Physical
kinetics, calibration and generalization require additional evaluations.

## Original four-stage roadmap

| Stage | Actual status |
| --- | --- |
| G1: endpoint, decomposition, spread and energy analysis | Completed on this limited eight-protein frozen-checkpoint panel |
| G2: additional training seeds | Not run; other seed checkpoints unavailable |
| G3: sampling check and conservative-training comparator | K=4/8/16 sampling component completed; training comparator not run |
| G4: alpha/retention frontier | Not run; original adaptation/retention assets unavailable |

The earlier G0 summary-receipt audit and technical pilot are complete in their
limited scope; exact reconstruction of the original evaluator remains unresolved.
Additional training experiments await the missing original assets.

## Compute and artifacts

The provider-reported charges at the saved snapshots total **$4.56762390**:
$1.23086024 for the initial panel and $3.33676366 for the extension. All sixteen
apps were confirmed stopped with zero tasks. A $2 late-billing allowance remains
held locally, and the $10 planning reserve remains untouched. These are saved provider charge snapshots; final invoices and account credit
balances are tracked separately.

- [Frozen protocol and sampling amendment](FROZEN_EVALUATION_PROTOCOL.md)
- [K=4 report](../reports/sampling-k4-v1/results.md)
- [K=8 report](../reports/sampling-k8-v1/results.md)
- [K=16 report](../reports/sampling-k16-v1/results.md)
- K=16 per-protein plot (submitted separately)
- [Independent K=4 audit](K4_AUDIT.md)
- [Sampling integrity audit](SAMPLING_AUDIT.md)

Operational receipts are preserved privately; the scientific reports above remain included.
