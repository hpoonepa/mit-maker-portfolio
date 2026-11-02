# SENBA frozen paired-evaluator report

Validation-panel descriptive results from a new evaluator; not an independent test result.

## Counts

- Records: 160; transition units: 160; proteins: 8; training seeds: 1; K: [16]
- Raw C-alpha coordinates: RAW_CA_COORDINATES_PRESENT (160/160)
- Maximum absolute MSE decomposition identity residual: 1.14e-13

## Equal-protein summaries

### Training seed 20260825 (8 proteins)

| Quantity | Candidate − source | Protein-bootstrap 95% interval |
| --- | ---: | ---: |
| centroid_rmsd | -0.01383 | [-0.02194, -0.007334] |
| mean_sample_rmsd | -0.06293 | [-0.07702, -0.04954] |
| energy_score | -0.006422 | [-0.01166, -0.001599] |
| ensemble_variance (spread; no desired sign) | -1.87 | — |
| pairwise_rmsd (spread; no desired sign) | -0.113 | — |

Persistence C-alpha RMSD: 11.63; candidate centroid-RMSD gain versus persistence: 1.606; source gain: 1.592.

## Boundaries

- Validation-panel results use a new evaluator and are not an exact reproduction of earlier results.
- All candidate-minus-source deltas are descriptive; no independent test-set claim is made.
- Spread changes have no desired sign and different K values are reported separately, never concatenated.
- The prespecified eight-protein validation panel is reused; it is not an independent test set and cannot support selection claims.
