# BoltzGen — Paper Crane Tool Adapter

BoltzGen is an all-atom binder generator (Wohlwend et al.). It emits full
structures with side chains in a single diffusion pass — no ProteinMPNN / AF2
chain required downstream — and is ligand-aware: an optional SDF or PDB ligand
can be supplied and the binding pocket is co-designed around it.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (normalized `DesignRequest`).
2. Reads `/inputs/target.pdb`.
3. Optionally reads a ligand file referenced by `request.ligand`
   (SDF or PDB — staged by the scheduler next to the target).
4. Writes `/outputs/designs/*.pdb` (all-atom) + matching `*.json` metrics.
5. Writes `/outputs/result.json` (normalized `DesignResult`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## What makes BoltzGen different

| | BindCraft | BoltzGen |
|---|---|---|
| Output | backbone + sequence (via MPNN) | backbone **and** side chains in one pass |
| Validation | built-in AF2 recycling | native all-atom confidence (pLDDT + side-chain confidence + clash score) |
| Ligand | not supported in-loop | first-class input (SDF / PDB) |
| Config | JSON | YAML |

Because BoltzGen is all-atom from the start, its native `sidechain_confidence`
and `clash_score` are meaningful early filters — the canonical Paper Crane
validator still re-scores everything afterwards with ipSAE / DockQ / etc.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream BoltzGen at a pinned SHA. |
| `manifest.json` | `ToolManifest` — catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for BoltzGen-specific `toolParams` (incl. optional `ligand`). |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `BoltzGenAdapter` — `prepare`/`run`/`parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Parameters

BoltzGen-specific knobs (all optional, passed via `DesignRequest.toolParams`):

| Param | Default | Notes |
|---|---|---|
| `num_designs` | 5 | Designs per seed. |
| `diffusion_steps` | 200 | All-atom reverse-diffusion steps (not AF2 recycles). |
| `temperature` | 0.1 | Sampling temperature; lower = more conservative. |
| `length_range` | `[60, 150]` | Binder length bounds (also readable from `constraints.lengthRange`). |
| `ligand` | — | Path to an SDF or PDB ligand. BoltzGen co-designs the pocket around it and emits a `ligand_rmsd` metric. |

## Upstream

- Source: `https://github.com/jwohlwend/boltzgen`
- Pinned SHA: `TODO_BOLTZGEN_SHA` (Dockerfile `ARG BOLTZGEN_SHA`)
- YAML-configured CLI: `python /opt/boltzgen/scripts/design.py --config ... --out ...`
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7 (tool SHAs pinned, adapter lives outside upstream).

To promote a new upstream version, set a commit SHA in CI build args, rebuild,
and bump `adapterVersion` in `manifest.json` if the wrapper changes.

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/boltzgen/requirements-dev.txt

# Fast unit tests (no BoltzGen install required)
pytest tools/boltzgen

# Full integration (runs the upstream pipeline — needs the built image)
pytest tools/boltzgen -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target  /inputs/target.pdb \
  --output  /outputs
```

which in turn runs BoltzGen once per seed:

```bash
python /opt/boltzgen/scripts/design.py \
  --config /outputs/workdir/config.yaml \
  --out    /outputs/designs \
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request,
the target PDB, and — if present — the ligand file into `/inputs`, launches
the container with the GPU profile declared in `manifest.json` (`A100-40GB`,
~90 s/design), streams stdout to the jobs DB, and on exit rsyncs `/outputs/`
to S3. The validator image then re-scores each design with the canonical
Paper Crane metric suite (ipSAE, DockQ, pTMEnergy, LIS, Overath, hotspot
contact, ESM2 pLL) — BoltzGen's own metrics (`plddt_mean`, `clash_score`,
`sidechain_confidence`, `hotspot_contact`, `ligand_rmsd`) live alongside and
stay available for users who want the native numbers.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 10
- `packages/tools-sdk/src/types.ts` — canonical contract
- `tools/bindcraft/` — sibling reference adapter (backbone + MPNN flow)
