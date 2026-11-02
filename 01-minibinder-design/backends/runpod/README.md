# Tri-objective scoring on RunPod

Scores designs on **Protenix + Boltz2 + ESMFold** and ranks them with the
objective derived from the DWV VP3 ground truth.

## Why these three

35 designs went out across two Adaptyv campaigns. 19 loaded onto the sensor,
**16 produced zero measured curves**, 1 bound (`l79_s469532_mpnn9`, KD 546/666 nM).

Where the one binder ranked among the 17 designs with full metrics:

| metric | value | rank |
|---|---|---|
| protenix ipTM | 0.9490 | **1/17** |
| protenix seed spread | 0.0006 | **1/17** (lowest) |
| esmfold2 ipTM | 0.8004 | **2/17** |
| ipSAE_min | 0.8279 | **10/20** |

What predicts **expression** (loaded vs. zero curves):

| metric | AUC | p |
|---|---|---|
| solublempnn delta | 0.725 | 0.12 |
| esmfold2 ipTM | 0.653 | 0.32 |
| solublempnn raw | 0.463 | 0.83 |
| **protenix ipTM** | **0.500** | **1.00** |

Two conclusions drive the design:

1. **The axes are retrospective hypotheses.** The panel motivates examining
   interface confidence and expression-oriented features separately. One
   positive and nonsignificant expression comparisons do not establish
   general predictors or independent biological mechanisms.
2. **ipSAE is demoted.** It would have ranked the only real binder 10th of 20.
   Still computed and reported, no longer the gate. The old
   `consensus_gate(metric_key="min_ipsae")` is preserved behind
   `LEGACY_IPSAE_GATE = False` in `src/tri_objective.py`.

**Honesty:** the binding axis rests on **one** positive and those ranks were
computed after the fact. The expression axis has 17–18 outcomes and **nothing
reaches p<0.05** (n=17, 10/10 split ≈ 30% power for AUC 0.70). Thresholds
marked `CALIBRATED` come from that single binder. Re-run
`src.tri_objective.calibrate()` on every new batch of ground truth.

## Build and push

```bash
docker build -t <user>/mosaic-tri:latest -f runpod/Dockerfile .
docker push <user>/mosaic-tri:latest
```

## Historical pod configuration

Prices below are recorded campaign-era estimates, not current quotes.

| setting | value | why |
|---|---|---|
| GPU | H100 80GB (A100 80GB fine) | ~$2.59/hr, ≈$0.23/design measured |
| Container disk | **≥ 60 GB** | RunPod has **no disk floor** — the default silently truncates the image mid-pull |
| Volume | ≥ 50 GB at `/workspace` | outputs survive a pod restart |
| Image | `<user>/mosaic-tri:latest` | |

## Run

```bash
export POD_HOST=213.x.x.x POD_PORT=22222      # DIRECT ssh, not the proxy
./runpod/launch_runpod.sh designs.fasta 5G51.cif
```

Runs detached under `nohup`, so an ssh drop cannot kill a multi-hour job.

```bash
# poll
ssh -p $POD_PORT root@$POD_HOST 'cat /workspace/outputs/DONE 2>/dev/null || tail -5 /workspace/logs/nohup.log'
# fetch
scp -P $POD_PORT root@$POD_HOST:/workspace/outputs/tri_scores.csv .
```

## Traps this bundle already handles

- **`pip install esm` is the wrong package.** ESMFold is `fair-esm[esmfold]`.
  Same trap for `protenix` and `boltz`: mosaic's real deps live in
  `[tool.uv.sources]`, which pip cannot see. Always `uv sync`, never `pip install -r`.
- **Two venvs, deliberately.** `/opt/mosaic/.venv` is JAX 0.9.1 (jax 0.10
  removed `ShapeDtypeStruct.vma` and breaks unpickling the protenix weights);
  `/opt/esmfold/.venv` is PyTorch. `MOSAIC_ESMFOLD_PYTHON` bridges them by
  subprocess. **Never pip into the mosaic venv** — the jax pin is load-bearing.
- **mosaic pinned to `bca3152`**, the first commit with `ProtenixV2()` and the
  last before the `8362af3` refactor breaks the pickled weights.
- **ColabFold MSA failures are transient.** The entrypoint retries 3× with
  backoff instead of dying.
- **`--protenix-seeds` must be ≥ 2** or the seed spread is undefined — which
  forfeits the strongest single discriminator in the panel. A single seed
  returns `nan`, never `0.0`, so it cannot be mistaken for perfect stability.
- **Use DIRECT ssh, not the RunPod proxy** — the proxy drops long connections.
- **Stop the pod when done.** It bills idle.

## Local use (no RunPod)

```bash
python validators/tri_consensus.py --sequences designs.fasta \
    --target-cif 5G51.cif --out tri_scores.csv --protenix-seeds 5
```

Unset `MOSAIC_ESMFOLD_PYTHON` to import ESMFold in-process instead of shelling out.

## Scoring without predictors

`scripts/consensus_rank.py` ranks a CSV you already have metrics for — no GPU:

```bash
python scripts/consensus_rank.py designs.csv -o ranked.csv
python scripts/consensus_rank.py labelled.csv --calibrate labelled.csv
```
