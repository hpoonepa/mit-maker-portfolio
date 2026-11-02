# Independent audit of the frozen K=4 panel

## Scope and conclusion

This audit independently recomputed the K=4 results from the 160 JSONL records in
the eight frozen run directories and checked them against the NPZ inputs, frozen
specifications, completion receipts, runtime receipts, public MarS-FM validation
split, and `FROZEN_EVALUATION_PROTOCOL.md`. The audit uses saved model outputs.

The records are complete and internally consistent for the specified new evaluator:
eight proteins, 20 unique physical transitions per protein, K=4 source and candidate
draws, ten ODE steps, and one released candidate training seed (`20260825`). The
independently recomputed equal-protein summaries match
`artifacts/reports/panel-k4-v1/analysis.json` to floating-point precision.

The primary centroid-RMSD difference favors the candidate by 0.02401 Å, or 0.217%
of the source value, with the same direction in all eight proteins. This small,
descriptive result uses a previously used validation panel, a new evaluator and
one training seed. The exploratory energy-score interval crosses zero, and the
candidate ensembles are less dispersed. At K=4, the energy-score direction is
uncertain and spread is lower.

All reported coordinate errors and spread scores are in individually
start-Kabsch-aligned C-alpha space. Alignment removes global pose. All-atom structural accuracy and physical kinetics
require separate measurements. The energy score is a statistical forecast score;
its distributional interpretation applies to this transformed coordinate
representation under iid forecast draws. Molecular energy and free energy are
separate quantities. The conditional eight-domain bootstrap holds the training
seed and sampled target trajectories fixed.

## Identity, pairing, and completion checks

- The observed protein set exactly matches the eight domains frozen in the new
  protocol and named in the published compact validation panel: `1e7uA04`,
  `1rquA01`, `1q16B03`, `1d1rA00`, `2k4qA00`, `2f2cA02`, `5k2mA01`, and
  `2dp9A01`. All eight occur in the pinned public MarS-FM `mdCATH_val.csv`.
- All eight completion receipts say `complete: true` with 20 transitions. The raw
  files contain 160 records and 160 runtime rows, with 160 unique full record-ID
  tuples and 160 unique `(protein, replica, start)` units. Every protein contributes
  exactly 20 units; there are no duplicate or missing units.
- Each observed replica/start pair equals its hash-bound NPZ transition metadata.
  Each protein uses replicas 0--4, four starts per replica, and a target exactly 50
  saved frames later in the same replica.
- Every protein uses inference seeds `20260904` through `20260923` in replica-major,
  start-minor order. For all 160 rows, source and candidate RNG-state hashes match
  both before and after generation. This verifies paired random streams; statistical
  independence of the four samples remains an assumption of the vectorized sampler.
- Every record reports angstrom units, `start_aligned`, K=4, ten ODE steps, the new
  evaluator identity, training seed `20260825`, and
  `NEW_EVALUATOR_NOT_PROVEN_OLD_REPRODUCTION`.
- The actual source and candidate checkpoints match their frozen SHA-256 identities:
  `f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879`
  and `f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c`.
- Every actual NPZ hash matches its frozen spec and every row-level data receipt:

| Protein | Actual and frozen NPZ SHA-256 |
| --- | --- |
| `1e7uA04` | `af6b09f5814a45c9244d4c4cfa817864b65b2953075253bcc4b6f50a59509ed0` |
| `1rquA01` | `27268d20e75e0d7ef9742bacd4a6b03ba2113d51275875f2d6b9147ade89343a` |
| `1q16B03` | `74385f86bc41f6cfc66db9ede153e8140fd256e381584dfa7a88c2bd5650f788` |
| `1d1rA00` | `0bc6c06b50b6f1120eeb83191f211633b493cbf86c3f3dae24b8e8341567c69c` |
| `2k4qA00` | `0dd0226c4f5a529770961937f48a6bb9740896e98d5082ebabcb38ef5f89a4a6` |
| `2f2cA02` | `60279746e35dfd12fe861673fd93b8e570d19eb170588e5f01990a35b82bac3d` |
| `5k2mA01` | `4f41f729ef347e6f084361abbf33e63c7a8977eb66dd9d82032370220b75d628` |
| `2dp9A01` | `bed68fdb00755b13e624cbc57eb53716299472abef31a520bc3130912a07133f` |

All seven expansion jobs have the same complete frozen code-hash map. The pilot and
expansion jobs have identical `data.py`, `inference.py`, and `metrics.py` hashes, but
their recorded `cloud.py` hashes differ (`0fb8c8...` for the pilot and `b084ef...`
for expansion). The record contracts and all checks above agree. The
historical source corresponding to the pilot’s `cloud.py` hash is absent from
the archive. The scope of that source change therefore remains unresolved.

## Independently recomputed results

All summaries first average the 20 transitions within each protein and then weight
the eight proteins equally. Deltas are candidate minus source; negative values favor
the candidate for error metrics and energy score. Percent change is
`(source - candidate) / source` and is descriptive.

| Quantity | Source | Candidate | Candidate - source | Source-relative reduction | Protein-bootstrap 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: |
| Centroid RMSD (Å), primary | 11.05817 | 11.03417 | -0.02401 | 0.217% | [-0.02882, -0.01870] |
| Mean individual-sample RMSD (Å) | 14.17187 | 14.11161 | -0.06026 | 0.425% | [-0.07275, -0.04774] |
| Energy score (Å), exploratory | 6.91371 | 6.91043 | -0.003278 | 0.047% | [-0.007674, 0.001153] |
| Finite-K population-mean MSE estimate (Å²) | 111.18038 | 111.08542 | -0.09496 | 0.085% | [-0.29867, 0.12011] |
| Ensemble variance (Å²), spread | 89.79118 | 88.35108 | -1.44010 | 1.604% lower | not inferentially reported |
| Mean pairwise RMSD (Å), spread | 14.51632 | 14.40235 | -0.11396 | 0.785% lower | not inferentially reported |

The percentile intervals use the report's prespecified 2,000 protein-level bootstrap
resamples and seed `20260904`. With only eight reused proteins, these intervals have
limited resolution and hold the training seed fixed.

### Per-protein deltas and directional counts

| Protein | Centroid RMSD (Å) | Mean sample RMSD (Å) | Energy score (Å) | Population-mean MSE estimate (Å²) | Ensemble variance (Å²) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `1e7uA04` | -0.02700 | -0.09092 | +0.00656 | +0.50517 | -2.67441 |
| `1rquA01` | -0.00815 | -0.03615 | +0.00030 | +0.12720 | -0.90968 |
| `1q16B03` | -0.03071 | -0.06431 | -0.00567 | -0.35013 | -1.65604 |
| `1d1rA00` | -0.02216 | -0.03559 | -0.00884 | -0.44223 | -0.58308 |
| `2k4qA00` | -0.02443 | -0.06899 | +0.00384 | -0.13406 | -1.63885 |
| `2f2cA02` | -0.02379 | -0.06892 | -0.00209 | -0.06376 | -1.89917 |
| `5k2mA01` | -0.03557 | -0.07017 | -0.01349 | -0.41143 | -1.36421 |
| `2dp9A01` | -0.02022 | -0.04703 | -0.00684 | +0.00957 | -0.79533 |

The candidate has lower centroid RMSD and mean individual-sample RMSD in 8/8
proteins. It has a lower exploratory energy score in 5/8 and a lower finite-K
population-mean MSE estimate in 5/8. Both spread summaries are lower in 8/8, while
interpreting spread requires comparison with the target distribution.

## Interpretation and limits

The primary result is a consistent but small conditional endpoint-error reduction:
0.024 Å in the equal-protein mean, only 0.217% of the source error. The bootstrap
interval excludes zero for this particular eight-protein panel, but the panel was
used in earlier development and only one trained checkpoint seed was evaluated.
The estimate is conditional on that panel and checkpoint seed.

The candidate's mean-sample and sample-MSE reductions occur alongside uniformly
lower ensemble spread. Contraction can improve squared and endpoint errors against a
single realized future without improving the full conditional distribution. The
energy score partially accounts for ensemble dispersion, but its mean difference is
only -0.00328 Å, improves on five proteins, and has a protein-bootstrap interval that
crosses zero. The energy-score direction remains uncertain at K=4.

The finite-K population-mean MSE diagnostic subtracts estimated sampling variance
from centroid MSE. Its macro difference is small, improves on five proteins, and its
bootstrap interval also crosses zero. At K=4 the correction is noisy and can be
negative for individual transitions. It subtracts Monte Carlo variance of the model draws to estimate squared error
of the model’s conditional mean against one observed target. Uncertainty in that
target remains; biological bias and conditional-mean calibration require
repeated-target analysis.

The exact MSE decomposition closes numerically: the maximum absolute residual over
all source and candidate records is `2.27e-13`. This checks implementation
consistency. K=16 prefix-preserving augmentation can measure finite-sample
sensitivity using the same proteins, physical transitions, training seed and
original four draws.

## Manuscript-ready paragraph

Using a prespecified new frozen-evaluator implementation, we compared the released seed-1 SENBA
checkpoint with its pinned source MarS-FM checkpoint on eight previously used mdCATH
validation domains (160 same-replica lag-50 transitions; K=4 paired samples per
model). Equal-domain mean centroid endpoint RMSD was 11.058 Å for the source and
11.034 Å for SENBA, a descriptive reduction of 0.024 Å (0.217%; 2,000-resample
protein-bootstrap interval for candidate minus source, -0.0288 to -0.0187 Å), with
the same direction in all eight domains. Mean individual-sample RMSD decreased by
0.0603 Å. However, SENBA ensembles were less dispersed, the exploratory energy-score
difference was -0.00328 Å with an interval spanning zero (-0.00767 to 0.00115 Å),
and only one training seed was available. The panel was reused after model development and scored with a new evaluator.
These findings measure a small conditional validation-panel endpoint difference
for the available checkpoint seed; the K=4 distribution-score direction remains
uncertain.
