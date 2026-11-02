# SENBA frozen paired-evaluator report

Validation-panel descriptive results from a new evaluator; not an independent test result.

## Counts

- Records: 160; transition units: 160; proteins: 8; training seeds: 1; K: [4]
- Raw C-alpha coordinates: RAW_CA_COORDINATES_PRESENT (160/160)
- Maximum absolute MSE decomposition identity residual: 2.27e-13

## Equal-protein summaries

### Training seed 20260825 (8 proteins)

| Quantity | Candidate − source | Protein-bootstrap 95% interval |
| --- | ---: | ---: |
| centroid_rmsd | -0.02401 | [-0.02882, -0.0187] |
| mean_sample_rmsd | -0.06026 | [-0.07275, -0.04774] |
| energy_score | -0.003278 | [-0.007674, 0.001153] |
| ensemble_variance (spread; no desired sign) | -1.44 | — |
| pairwise_rmsd (spread; no desired sign) | -0.114 | — |

Persistence C-alpha RMSD: 11.63; candidate centroid-RMSD gain versus persistence: 0.6002; source gain: 0.5762.

## Boundaries

- Validation-panel results use a new evaluator and are not an exact reproduction of earlier results.
- All candidate-minus-source deltas are descriptive; no independent test-set claim is made.
- Spread changes have no desired sign and different K values are reported separately, never concatenated.
- The prespecified eight-protein validation panel is reused; it is not an independent test set and cannot support selection claims.
