# SENBA frozen paired-evaluator report

Validation-panel descriptive results from a new evaluator; not an independent test result.

## Counts

- Records: 160; transition units: 160; proteins: 8; training seeds: 1; K: [8]
- Raw C-alpha coordinates: RAW_CA_COORDINATES_PRESENT (160/160)
- Maximum absolute MSE decomposition identity residual: 1.14e-13

## Equal-protein summaries

### Training seed 20260825 (8 proteins)

| Quantity | Candidate − source | Protein-bootstrap 95% interval |
| --- | ---: | ---: |
| centroid_rmsd | -0.01887 | [-0.02257, -0.01545] |
| mean_sample_rmsd | -0.06517 | [-0.07889, -0.05213] |
| energy_score | -0.006037 | [-0.008406, -0.00359] |
| ensemble_variance (spread; no desired sign) | -1.821 | — |
| pairwise_rmsd (spread; no desired sign) | -0.1183 | — |

Persistence C-alpha RMSD: 11.63; candidate centroid-RMSD gain versus persistence: 1.261; source gain: 1.242.

## Boundaries

- Validation-panel results use a new evaluator and are not an exact reproduction of earlier results.
- All candidate-minus-source deltas are descriptive; no independent test-set claim is made.
- Spread changes have no desired sign and different K values are reported separately, never concatenated.
- The prespecified eight-protein validation panel is reused; it is not an independent test set and cannot support selection claims.
