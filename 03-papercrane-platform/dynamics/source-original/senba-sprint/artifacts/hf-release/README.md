---
license: mit
base_model: valencelabs/mars-fm
datasets:
- compsciencelab/mdCATH
library_name: pytorch
tags:
- protein-dynamics
- molecular-dynamics
- flow-matching
- mars-fm
- mdcath
- biology
- pytorch
---

# Senba

Senba is a source-anchored adaptation of [MarS-FM](https://github.com/valence-labs/mars-fm)
(Valence Labs, ICLR 2026) for mdCATH backbone transitions at 450 K and one 50-frame lag.
It is published as a **validation-stage candidate** together with the selection receipt, every
comparison, and the preregistered protocols, so the claim below can be audited.

Release page: <https://senba.papercrane.bio/>

## Identity

| Field | Value |
| --- | --- |
| Run | `mars-fm-e010-a07350-exactlag-128x32-20260825-s1-v1` |
| Checkpoint | `senba.ckpt` · 136,711,098 bytes · SHA-256 `f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c` |
| Base model | [`valencelabs/mars-fm`](https://huggingface.co/valencelabs/mars-fm) revision `1e957cd4b9f1a054ceb0c2104f40ba6f3cc0d8d0`, `mars_fm.ckpt` SHA-256 `f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879` |
| Source code | [`valence-labs/mars-fm`](https://github.com/valence-labs/mars-fm) commit `4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946` |
| Architecture | Unchanged MarS-FM; 34,152,521 parameters, all trainable during adaptation |
| Adaptation data | mdCATH, bounded development subset of 128 train and 32 validation domains (manifest `sha256:163ab0043d86b5a2731e1b1a233af27fb069049897d657fd5c39bd54b1343b3f`), 450 K replicas |
| Objective | Observed same-replica frame pairs separated by exactly 50 frames (`exact_lag`), cluster-balanced starts, no replica crossing |
| Anchoring | Source-checkpoint weight interpolation, α = 0.0735 (7.35% of the fine-tuning displacement retained) |
| Frozen | 2026-08-25 |
| Test records opened | 0 |

The checkpoint is a PyTorch Lightning checkpoint. Its `hyper_parameters` contain an
`argparse.Namespace`, so loading under `torch>=2.6` requires
`torch.serialization.add_safe_globals([argparse.Namespace])` (the example script does this).

## How it was made

1. **Parent fine-tune.** All MarS-FM parameters were fine-tuned from the pinned source checkpoint
   for 10 epochs (160 optimizer updates, 30,720 sampled exact-lag transitions), batch size 8
   domains, learning rate 3e-6, fresh Adam, seed 20260825, on one NVIDIA H100 in 121.80 s (peak
   64.7 GB allocated). Validation loss on a fixed transition population with replayed flow
   randomness moved from the replayed source value 1.724479 to 1.693136. Parent run
   `mars-fm-epoch-sweep-e010-exactlag-128x32-20260825-s1-v1`, checkpoint SHA-256
   `1bd5c20b5f3aa8587dce6440af6580f0c2def98d0b868a39969ef854bd729a25`.
2. **Anchoring.** The parent damaged the source model's equilibrium ensembles and was rejected as a
   deployable candidate. Senba is `source + 0.0735 · (parent − source)` in weight space.
3. **Selection.** α was chosen on the frozen epoch-sweep protocol, then the candidate had to pass the
   full-panel transition comparison and the equilibrium-retention suite without any change to the
   checkpoint, inference settings, metrics, or population.


### Full eligible validation panel (28 domains, ≤256 residues)

| Comparison | Ensemble-mean endpoint C-alpha RMSD improvement | 95% CI | Domains improved |
| --- | --- | --- | --- |
| vs source MarS-FM | +0.0326 Å | [0.0253, 0.0401] | 27 / 28 |
| vs coordinate persistence | +0.436 Å | [0.203, 0.681] | 22 / 28 |
| vs previous Senba (5-epoch, α = 0.08) | +0.00216 Å | [0.00086, 0.00345] | 22 / 28 |

Secondary summaries on the same outputs: best-of-k RMSD improvement vs source +0.0372 Å,
single-sample RMSD improvement vs source +0.0689 Å, displacement-magnitude MAE improvement
+0.0292 Å, direction-cosine improvement +0.0014. Per-domain rows are in
`receipts/full-transition-comparison.json`.

### Equilibrium retention (8 domains, official tree sampling, 500 samples)

Degradation is measured in each observable's unfavorable direction against source MarS-FM;
negative values are improvements. Limits were frozen before any candidate output existed.

| Observable | Mean degradation | 95% CI | Mean limit | Worst domain / limit | Pass |
| --- | --- | --- | --- | --- | --- |
| DCCM MAE | −0.000660 | [−0.001625, 0.000285] | 0.005 | 0.001768 / 0.01 | ✓ |
| Native-contact fraction W1 | +0.000271 | [−0.001594, 0.001946] | 0.015 | 0.003055 / 0.03 | ✓ |
| Pairwise RMSD W1 (Å) | −0.0437 | [−0.1260, 0.0493] | 0.25 | 0.2076 / 0.5 | ✓ |
| PCA subspace RMSIP | +0.00416 | [−0.00023, 0.01075] | 0.03 | 0.02536 / 0.06 | ✓ |
| Clash fraction | −0.0000012 | [−0.0000246, 0.0000225] | 0.0005 | 0.0000575 / 0.001 | ✓ |
| Radius of gyration W1 (Å) | −0.0422 | [−0.0775, −0.0080] | 0.15 | 0.0319 / 0.3 | ✓ |
| RMSF RMSE (Å) | −0.0222 | [−0.0776, 0.0396] | 0.15 | 0.1471 / 0.3 | ✓ |

### Replication (three independently trained parents, 8-domain compact panel)

| Parent seed | Gain vs source | 95% CI | Domains improved | Matched difference vs previous Senba |
| --- | --- | --- | --- | --- |
| 1 (20260825) | +0.0301 Å | [0.0184, 0.0431] | 8 / 8 | +0.00308 Å |
| 2 (20260826) | +0.0229 Å | [0.0133, 0.0343] | 8 / 8 | −0.00110 Å |
| 3 (20260827) | +0.0290 Å | [0.0183, 0.0386] | 8 / 8 | +0.00557 Å |

Three-seed mean gain over source: +0.0273 Å. Mean matched difference vs the previous Senba:
+0.00252 Å. The seed-2 difference is negative and its interval crosses zero, so the correct reading
is a modest average improvement over the previous checkpoint, not a uniform win at every seed.

## Intended use

Research inspection of single-chain, all-heavy-atom protein structures of at most 256 residues:
draw independent samples of where MarS-FM-style flow matching places the backbone after the
trained lag, and compare against source MarS-FM.

## How to run

```bash
git clone https://github.com/valence-labs/mars-fm.git && cd mars-fm
git checkout 4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946
pip install "torch>=2.5" "pytorch-lightning>=2.4" torchdiffeq "numpy<2" \
            dm-tree fair-esm biopython pandas scipy
hf download pikachuandme1/senba senba.ckpt inference_example.py --local-dir senba

PYTHONPATH=. python senba/inference_example.py \
  --pdb 1ubq.pdb --chain A \
  --checkpoint senba/senba.ckpt \
  --expect-sha256 f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c \
  --samples 8 --ode-steps 10 --seed 20260904 \
  --out senba-1ubq.pdb
```

The script writes a multi-model PDB: MODEL 1 is the input, MODELS 2 to K+1 are K independent
draws. It refuses structures with missing heavy atoms, non-standard residues, or several chains
rather than silently zero-filling, and warns when the input exceeds the validated 256 residues.
A GPU is recommended; CPU works but is slow.

To load the checkpoint yourself, follow `inference_example.py`: build the same batch layout as
MarS-FM (`torsions`, `torsion_mask`, `trans`, `rots`, `seqres`, `mask`), then call
`MarSModule.inference(batch, num_steps=10)`.

## Files

| Path | Contents |
| --- | --- |
| `senba.ckpt` | The selected checkpoint, byte-identical to the receipt hash |
| `inference_example.py` | Sampling script against the pinned MarS-FM source |
| `receipts/selection-v2.json` | Selection receipt (`dynaview-mars-fm-epoch-sweep-selection-v2`) |
| `receipts/interpolation-config.json`, `receipts/interpolation-result.json` | Anchoring receipt for the selected checkpoint |
| `receipts/parent/training-config.json`, `receipts/parent/training-result.json` | Seed-1 parent fine-tune receipt with per-epoch validation losses |
| `receipts/full-transition-comparison.json` | 28-domain transition comparison vs source and persistence |
| `receipts/head-to-head-vs-previous-senba.json` | 28-domain comparison vs the previous Senba checkpoint |
| `receipts/equilibrium-suite-comparison.json` | Seven-observable retention suite with per-domain rows |
| `receipts/replications/seed2/`, `receipts/replications/seed3/` | Seed-2 and seed-3 parent, anchoring, and compact-panel receipts |
| `protocols/` | The four preregistered protocols, frozen before the outputs they govern existed |
| `release-manifest.json` | SHA-256 of every published file |

## Compute

The three ten-epoch parents took 378.21 H100-seconds in aggregate (121.80, 126.07 mean). Observed
Modal billing for the whole 2026-08-25 search and validation campaign was $19.45 ($10.60
adaptation, $8.85 validation).

## License and attribution

Weights and code: MIT (see `LICENSE`). MarS-FM source model and code are MIT, Copyright (c) 2026
Valence Labs. The adaptation data, mdCATH, is CC BY 4.0; attribute it when you use these weights.

## Citation

If you use Senba, cite MarS-FM and mdCATH:

```bibtex
@inproceedings{marsfm2026,
  title     = {MarS-FM: Generative Modeling of Molecular Dynamics via Markov State Models},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2026},
  note      = {arXiv:2509.24779}
}

@article{mdcath2024,
  title   = {mdCATH: A Large-Scale MD Dataset for Data-Driven Computational Biophysics},
  journal = {arXiv preprint arXiv:2407.14794},
  year    = {2024}
}
```

Senba itself: Paper Crane, "Senba: a source-anchored MarS-FM adaptation for mdCATH transitions,"
model release, 2026, <https://huggingface.co/vkali08/senba>.
