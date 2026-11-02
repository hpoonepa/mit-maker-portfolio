# Boltz-2 — Paper Crane Tool Adapter

Boltz-2 is an open biomolecular structure predictor (MIT License). Paper Crane
uses it primarily as a **binder validator** — given a target sequence plus one
or more candidate binder sequences, Boltz-2 co-folds the complex and emits
pLDDT / pTM / ipTM / PAE confidence metrics. It is also exposed in the catalog
as a standalone structure-prediction tool.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (Boltz-2 request — see `schemas/input.json`).
2. Optionally reads `/inputs/target.pdb` (used as a template if present).
3. Writes `/outputs/workdir/seed_<N>/out/prediction_*.cif` + matching `*.json`
   metrics for each binder.
4. Writes `/outputs/result.json` (see `schemas/output.json`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Installs `boltz==2.0.0` from PyPI on top of `ghcr.io/papercrane/base-cuda12`. |
| `manifest.json` | `ToolManifest` — catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the Boltz-2 request payload. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `Boltz2Adapter` — `prepare`/`run`/`parse`. Emits Boltz-2 YAML config. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/jwohlwend/boltz`
- Distribution: `pip install boltz==2.0.0` (PyPI)
- Pinned build arg: `BOLTZ2_SHA=TODO` (Dockerfile `ARG`). For reproducible
  image rebuilds, set this to a release tag / commit SHA when the upstream
  wheel is updated; bump `adapterVersion` in `manifest.json` if the wrapper
  changes.

## Model weights

Boltz-2's weights (~5 GB) are **not** baked into the image — the adapter
relies on the platform mounting a persistent Modal volume at `/root/.boltz`
(see `BOLTZ_CACHE` env var in the Dockerfile). On the first job the upstream
CLI downloads weights into this volume; subsequent jobs reuse the cache.

**Platform responsibility:** mount a shared volume at the path set by
`BOLTZ_CACHE` when scheduling a Boltz-2 container. See plan 03
(job scheduler) for the volume provisioning rules.

## Request shape

Boltz-2 takes a different request shape from the generic `DesignRequest`
because it's a validator, not a generator:

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
    "diffusion_samples": 5
  }
}
```

The adapter emits one Boltz-2 YAML config per binder:

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
pip install -r tools/boltz2/requirements-dev.txt

# Fast unit tests (no Boltz install required)
pytest tools/boltz2

# Full integration (runs the upstream Boltz CLI — needs the built image)
pytest tools/boltz2 -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target  /inputs/target.pdb \
  --output  /outputs
```

## How Paper Crane runs this adapter

Boltz-2 is **chained after** design tools (BindCraft, RFdiffusion+MPNN) in the
default pipeline: the job scheduler (plan 03) collects the design tool's
`/outputs/result.json`, hands each `(sequence, seed)` pair to this adapter as a
binder entry, and rsyncs Boltz-2's structural predictions to S3. The validator
image then re-scores each prediction with the canonical Paper Crane metric
suite (ipSAE, DockQ, pTMEnergy, LIS, Overath, hotspot contact, ESM2 pLL) —
Boltz-2's own metrics (`plddt_mean`, `plddt_binder`, `ptm`, `iptm`,
`ipae_mean`, `per_chain_ptm`) stay alongside for users who want the native
numbers.

Users can also invoke Boltz-2 directly from the catalog for general structure
prediction — the adapter doesn't assume the request came from a design tool.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 10 — catalog entry §8
- `packages/tools-sdk/src/types.ts` — canonical contract
- `tools/bindcraft/` — reference adapter layout
