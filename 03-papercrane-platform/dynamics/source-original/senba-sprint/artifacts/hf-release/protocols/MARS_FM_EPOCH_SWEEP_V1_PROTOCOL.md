# MarS-FM exact-lag epoch-sweep v1 development protocol

Status: frozen development sweep; no test, final-model, state-of-the-art, or
commercial claim.

Frozen on 2026-08-25 before launching any run in this sweep or inspecting any
new candidate output.

## Question

The existing five-epoch exact-lag parent ended with validation loss still
decreasing. This sweep asks whether a longer exact-lag fine-tune, followed by
source-weight anchoring, produces a larger endpoint improvement without
damaging the source model's equilibrium ensemble.

This is a retrospective development study. The 128-train/32-validation subset
and the 28 sequence-length-eligible validation proteins were used by the prior
Anchor08 program. Results from this sweep cannot be described as pristine
validation. The 495-record standard test partition remains unopened.

## Fixed training contract

Every parent starts from the same pinned public MarS-FM checkpoint and changes
only the epoch budget.

- Source checkpoint SHA-256:
  `f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879`.
- MarS-FM source revision:
  `4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946`.
- Development subset semantic SHA-256:
  `163ab0043d86b5a2731e1b1a233af27fb069049897d657fd5c39bd54b1343b3f`.
- Roles: 128 train domains and 32 validation domains, with no test records.
- Temperature: 450 K.
- Objective: observed same-replica pairs separated by exactly 50 frames.
- Trainable scope: all 34,152,521 parameters.
- Optimizer: fresh Adam state from the public checkpoint.
- Learning rate: `3e-6`.
- Batch size: 8.
- Seed: `20260825`.
- Validation population and flow randomness: fixed and replayed.
- Epoch budgets: `[5, 10, 20, 40, 80, 160]`.

Each epoch contains 16 optimizer steps, so the parent budgets contain
`[80, 160, 320, 640, 1280, 2560]` optimizer steps.

## Source-anchor grid

Longer parents can move farther from the source checkpoint, so a fixed
interpolation coefficient would confound training length with update size.
Each parent is therefore interpolated at four coefficients chosen so that the
heuristic product `epochs * alpha` is one of `[0.20, 0.30, 0.40, 0.60]`.
This product is a grid-design device, not a physical quantity or an assumption
that weight displacement is linear in epochs.

| Epochs | Interpolation coefficients |
| ---: | --- |
| 5 | `0.04`, `0.06`, `0.08`, `0.12` |
| 10 | `0.02`, `0.03`, `0.04`, `0.06` |
| 20 | `0.01`, `0.015`, `0.02`, `0.03` |
| 40 | `0.005`, `0.0075`, `0.01`, `0.015` |
| 80 | `0.0025`, `0.00375`, `0.005`, `0.0075` |
| 160 | `0.00125`, `0.001875`, `0.0025`, `0.00375` |

All 24 interpolated checkpoints must be created and screened. A missing or
failed run is reported, not silently replaced.

## Development screen

The source and every candidate use the same compact eight-protein panel, all
five replicas, four fixed starts per replica, four samples per start, exact lag
50, ten ODE steps, and inference seed `20260825`. Proteins are the bootstrap
unit with 100,000 resamples and bootstrap seed `20260825`.

A candidate remains eligible only if:

1. its parent improves the fixed paired validation loss over the source;
2. its mean ensemble-endpoint RMSD improvement over source is positive with a
   95% protein-bootstrap interval above zero;
3. at least six of eight proteins improve over source;
4. its mean improvement over coordinate persistence is positive; and
5. it passes all seven existing equilibrium-retention limits on the fixed
   `1e7uA04` pilot using breadth 200, 500 retained samples, 50 ODE steps, and
   seed `20260825`.

Among eligible candidates, select the largest mean ensemble-endpoint RMSD
improvement over source. An exact tie is broken by fewer epochs, then by the
smaller interpolation coefficient.

If the selected candidate uses 160 epochs, the epoch boundary is unresolved.
Extend the parent grid to 320 and 640 epochs with the same four heuristic
products before selecting a final configuration. Otherwise do not extend the
grid after observing results.

## Qualification after selection

Freeze the selected epoch count, interpolation coefficient, checkpoint,
inference settings, and selection receipt before further evaluation. Then:

1. run the selected seed-1 candidate on all 28 eligible validation proteins;
2. repeat the exact training and interpolation configuration with seeds
   `20260826` and `20260827` and run the compact transition panel;
3. run the existing eight-protein equilibrium-retention aggregate for the
   selected seed-1 checkpoint; and
4. leave the standard test partition unopened.

These qualification results remain development evidence because the
validation population was previously inspected. Any new external or test
claim requires a separately frozen untouched evaluation boundary.
