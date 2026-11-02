# BindCraft — Paper Crane Tool Adapter

BindCraft is an end-to-end protein binder design tool (hallucination + built-in
AF2 validation, Pacesa et al.). This directory is the reference Paper Crane tool
adapter — every other tool under `tools/` follows the same layout.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (normalized `DesignRequest`).
2. Reads `/inputs/target.pdb`.
3. Writes `/outputs/designs/*.pdb` + matching `*.json` metrics.
4. Writes `/outputs/result.json` (normalized `DesignResult`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream BindCraft at a pinned SHA. |
| `manifest.json` | `ToolManifest` — catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for BindCraft-specific `toolParams`. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `BindCraftAdapter` — `prepare`/`run`/`parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/martinpacesa/BindCraft`
- Pinned SHA: `TODO_BINDCRAFT_SHA` (Dockerfile `ARG BINDCRAFT_SHA`)
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7 (tool SHAs pinned, adapter lives outside upstream).

To promote a new upstream version, set a commit SHA in CI build args, rebuild,
and bump `adapterVersion` in `manifest.json` if the wrapper changes.

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/bindcraft/requirements-dev.txt

# Fast unit tests (no BindCraft install required)
pytest tools/bindcraft

# Full integration (runs the upstream pipeline — needs the built image)
pytest tools/bindcraft -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target  /inputs/target.pdb \
  --output  /outputs
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request
and target PDB into `/inputs`, launches the container with the GPU profile
declared in `manifest.json` (`A100-40GB`, ~140 s/design), streams stdout to the
jobs DB, and on exit rsyncs `/outputs/` to S3. The validator image then
re-scores each design with the canonical Paper Crane metric suite (ipSAE,
DockQ, pTMEnergy, LIS, Overath, hotspot contact, ESM2 pLL) — BindCraft's own
metrics (`iptm`, `plddt`, `i_pae`, `hotspot_contact`) live alongside and stay
available for users who want the native numbers.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 10
- `packages/tools-sdk/src/types.ts` — canonical contract
