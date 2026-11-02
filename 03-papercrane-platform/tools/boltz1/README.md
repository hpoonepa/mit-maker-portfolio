# Boltz-1 — Paper Crane Tool Adapter

Boltz-1 is an open biomolecular structure predictor (MIT License) — the older,
lighter sibling of Boltz-2. Same upstream repo (`jwohlwend/boltz`), different
model checkpoint: smaller weights (~2 GB vs ~5 GB), lower activation footprint
(fits on a 40 GB A100 vs 80 GB), and ~35 % faster per design. Paper Crane
uses it primarily as a **binder validator** — given a target sequence plus one
or more candidate binder sequences, Boltz-1 co-folds the complex and emits
pLDDT / pTM / ipTM / PAE confidence metrics. It is also exposed in the catalog
as a standalone structure-prediction tool for cheaper / bulk jobs.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (Boltz-1 request — see `schemas/input.json`).
2. Optionally reads `/inputs/target.pdb` (used as a template if present).
3. Writes `/outputs/workdir/seed_<N>/out/prediction_*.cif` + matching `*.json`
   metrics for each binder.
4. Writes `/outputs/result.json` (see `schemas/output.json`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Installs `boltz==1.0.0` from PyPI on top of `ghcr.io/papercrane/base-cuda12`. |
| `manifest.json` | `ToolManifest` — catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the Boltz-1 request payload. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `Boltz1Adapter` — `prepare`/`run`/`parse`. Emits Boltz YAML config. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/jwohlwend/boltz` (same repo as Boltz-2 — the
  CLI dispatches by checkpoint).
- Distribution: `pip install boltz==1.0.0` (PyPI)
- Pinned build arg: `BOLTZ1_SHA=TODO_BOLTZ1_SHA` (Dockerfile `ARG`). For
  reproducible image rebuilds, set this to a release tag / commit SHA when
  the upstream wheel is updated; bump `adapterVersion` in `manifest.json`
  if the wrapper changes.

## Model weights

Boltz-1's weights (~2 GB) are **not** baked into the image — the adapter
relies on the platform mounting a persistent Modal volume at `/root/.boltz`
(see `BOLTZ_CACHE` env var in the Dockerfile). On the first job the upstream
CLI downloads weights into this volume; subsequent jobs reuse the cache.
The same cache volume can be shared with the Boltz-2 adapter — the upstream
CLI keys on the checkpoint name.

**Platform responsibility:** mount a shared volume at the path set by
`BOLTZ_CACHE` when scheduling a Boltz-1 container. See plan 03
(job scheduler) for the volume provisioning rules.

## Request shape

Boltz-1 takes the same request shape as Boltz-2 — the two adapters are
drop-in substitutes at the wire level:

```json
{
  "targetSeq": "MKTAYIAK...",
  "targetPdb": "/inputs/target.pdb",
  "binders": [
    { "sequence": "MKTAYIAKQR...", "seed": 0 }
  ],
  "params": {
    "recycling_steps": 3,
    "sampling_steps": 200,
    "diffusion_samples": 3
  }
}
```

The adapter emits one Boltz YAML config per binder:

```yaml
version: 1
sequences:
  - protein:
      id: A                  # target
      sequence: <TARGET_SEQ>
  - protein:
      id: B                  # binder
      sequence: <BINDER_SEQ>
templates:
  - cif_url: /inputs/target.pdb   # optional
```

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/boltz1/requirements-dev.txt

# Fast unit tests (no Boltz install required)
pytest tools/boltz1

# Full integration (runs the upstream Boltz CLI — needs the built image)
pytest tools/boltz1 -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target  /inputs/target.pdb \
  --output  /outputs
```

## When to use Boltz-1 vs Boltz-2

| Consideration | Boltz-1 | Boltz-2 |
|---|---|---|
| GPU | A100-40GB | A100-80GB |
| RAM | 24 GB | 40 GB |
| Est. sec / design | ~70 | ~110 |
| Accuracy | lower | higher |
| Best for | bulk pre-screen, cost-sensitive jobs | final validation, high-stakes designs |

The default Paper Crane pipeline picks Boltz-2; users can fall back to Boltz-1
for large candidate pools where cost dominates accuracy (e.g. top-1000 screen
before a top-100 Boltz-2 rerank).

## How Paper Crane runs this adapter

Boltz-1 is **chained after** design tools (BindCraft, RFdiffusion+MPNN) in the
bulk pipeline: the job scheduler (plan 03) collects the design tool's
`/outputs/result.json`, hands each `(sequence, seed)` pair to this adapter as a
binder entry, and rsyncs Boltz-1's structural predictions to S3. The validator
image then re-scores each prediction with the canonical Paper Crane metric
suite (ipSAE, DockQ, pTMEnergy, LIS, Overath, hotspot contact, ESM2 pLL) —
Boltz-1's own metrics (`plddt_mean`, `plddt_binder`, `ptm`, `iptm`,
`ipae_mean`, `per_chain_ptm`) stay alongside for users who want the native
numbers.

Users can also invoke Boltz-1 directly from the catalog for general structure
prediction — the adapter doesn't assume the request came from a design tool.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 10 — catalog entry §8
- `packages/tools-sdk/src/types.ts` — canonical contract
- `tools/boltz2/` — sibling adapter (same upstream repo, newer checkpoint)
- `tools/bindcraft/` — reference adapter layout
