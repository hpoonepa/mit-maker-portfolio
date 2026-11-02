# Combined Labeled De-Novo Dataset — Counts (from real downloads)

Built by `scripts/combine_datasets.py` from Overath 2025 + Proteinbase (28 Jan 2026) + BindCraft SI.
PPB-Affinity (~12,063 Kd rows) held separately = transfer/pretrain only (off-distribution).

## Label rules (defensible, blueprint-aligned)
- **Proteinbase**: designs carry MULTIPLE replicate binding evals → label = **majority vote** (tie → binder),
  **conditioned on expression** (`P(binds|expressed)`): non-expressing designs are dropped, not counted as
  non-binders (expression failure ≠ tested non-binder).
- **Cross-source duplicate sequences**: unanimous label kept; **conflicting labels dropped** (16) and logged.

## Headline
- **Unique sequences (deduped): 5,721** — 849 binders / 4,872 non-binders (~14.8% positive)
- **Distinct targets (union): 41**
- **Testable (well-powered, ≥10 pos & ≥10 neg): 11 targets** → 11 LOTO folds
- **Relaxed testable (≥5 pos & ≥5 neg): 24 targets**

## The 11 testable (LOTO) targets
| Target | pos | neg | note |
|---|---|---|---|
| FGFR2 | 193 | 1930 | best fold |
| EGFR | 141 | 767 | |
| NIPAH | 103 | 781 | license unclear → validation-only for a shippable model |
| MDM2 | 61 | 60 | best class balance |
| IL7R | 59 | 154 | |
| PDL1 | 58 | 119 | |
| INSULINR | 41 | 111 | |
| PDGFRB | 18 | 12 | |
| MZB1 | 15 | 15 | |
| PD1 | 13 | 40 | |
| PMVK | 10 | 19 | |

## Fixed this pass
- **Nipah parse bug**: was 1 pos / 926 neg (last-eval-wins discarded replicate positives) → now **103/781** via majority vote. Nipah is now a testable fold.
- **+100 positives** recovered overall (749 → 849) from correct replicate handling.
- **16 cross-source label conflicts** now explicitly dropped + logged (was silent first-wins).
