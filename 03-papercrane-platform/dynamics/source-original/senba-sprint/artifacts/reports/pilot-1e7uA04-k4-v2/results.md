# SENBA frozen paired-evaluator report

Validation-panel descriptive results from a new evaluator; not an independent test result.

## Counts

- Records: 20; transition units: 20; proteins: 1; training seeds: 1; K: [4]
- Raw C-alpha coordinates: RAW_CA_COORDINATES_PRESENT (20/20)
- Maximum absolute MSE decomposition identity residual: 8.53e-14

## Equal-protein summaries

### Training seed 20260825 (1 proteins)

| Quantity | Candidate − source | Protein-bootstrap 95% interval |
| --- | ---: | ---: |
| centroid_rmsd | -0.027 | [-0.027, -0.027] |
| mean_sample_rmsd | -0.09092 | [-0.09092, -0.09092] |
| energy_score | 0.006557 | [0.006557, 0.006557] |
| ensemble_variance (spread; no desired sign) | -2.674 | — |
| pairwise_rmsd (spread; no desired sign) | -0.1949 | — |

Persistence C-alpha RMSD: 13.35; candidate centroid-RMSD gain versus persistence: 0.4194; source gain: 0.3924.

## Boundaries

- Validation-panel results use a new evaluator and are not an exact reproduction of earlier results.
- All candidate-minus-source deltas are descriptive; no independent test-set claim is made.
- Spread changes have no desired sign and different K values are reported separately, never concatenated.
- TECHNICAL_PILOT_ONLY: one protein gives a degenerate protein bootstrap; no scientific significance or inference is reported.
