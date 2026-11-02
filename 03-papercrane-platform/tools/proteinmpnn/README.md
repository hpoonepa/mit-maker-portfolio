# ProteinMPNN — Paper Crane Tool Adapter

ProteinMPNN (Dauparas et al., 2022) designs sequences for a fixed backbone via
inverse folding. In the Paper Crane catalog it is the canonical sequence-design
tool and the default downstream step for any backbone-generating tool
(RFdiffusion, Chroma, etc.) — see `docs/plans/02-tool-integration.md` §8.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships — same TODO pattern as BindCraft).

At runtime the container:

1. Reads `/inputs/request.json` (ProteinMPNN request, `schemas/input.json`).
2. Reads `/inputs/backbones/*.pdb` (one or more backbones staged by the scheduler).
3. Writes `/outputs/designs/*.fasta` + matching `*.json` metrics (one per design).
4. Writes `/outputs/result.json` (normalized `DesignResult`, `schemas/output.json`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

### Input shape vs BindCraft

Where BindCraft takes `{ targetPdb, hotspots, ... }`, ProteinMPNN takes
`{ backbones, seeds, params }`. There is no target and no hotspot list —
ProteinMPNN only sees a backbone and writes sequences for it. That is the main
deviation from `tools/bindcraft/` and is reflected in the schemas, fixtures,
and the `--backbones` (directory) entrypoint flag instead of `--target`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream ProteinMPNN at a pinned SHA. |
| `manifest.json` | `ToolManifest` catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the normalized ProteinMPNN request. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `ProteinMPNNAdapter` — `prepare` / `run` / `parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/dauparas/ProteinMPNN`
- Pinned SHA: `TODO_PROTEINMPNN_SHA` (Dockerfile `ARG PROTEINMPNN_SHA`)
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7 (tool SHAs pinned, adapter lives outside upstream).

To promote a new upstream version, set a commit SHA in CI build args, rebuild,
and bump `adapterVersion` in `manifest.json` if the wrapper changes.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `temperature` | `0.1` | Sampling temperature; lower = more deterministic. |
| `omit_aas` | `"CX"` | AAs to exclude. Default removes cysteines and the non-standard `X`. |
| `num_seq_per_target` | `1` | Sequences per backbone per seed. |
| `fixed_positions` | `null` | Optional `{ chain: [resi, ...] }` map of positions to keep fixed. |

Upstream CLI shape invoked inside the container:

```bash
python /opt/proteinmpnn/protein_mpnn_run.py \
  --pdb_path <backbones-dir> \
  --out_folder <outputs-dir> \
  --num_seq_per_target <N> \
  --sampling_temp <T> \
  --omit_AAs <omit_aas> \
  --seed <seed>
```

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/proteinmpnn/requirements-dev.txt

# Fast unit tests (no ProteinMPNN install required)
pytest tools/proteinmpnn

# Full integration (runs the upstream CLI — needs the built image)
pytest tools/proteinmpnn -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request    /inputs/request.json \
  --backbones  /inputs/backbones \
  --output     /outputs
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request
and backbone PDBs into `/inputs`, launches the container with the GPU profile
declared in `manifest.json` (`A10`, ~4 s/design), streams stdout to the jobs
DB, and on exit rsyncs `/outputs/` to S3. The validator image then re-scores
each design with the canonical Paper Crane metric suite — ProteinMPNN's native
`score` and `confidence_mean` remain alongside for users who want the raw
numbers.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 8 (catalog row)
- `packages/tools-sdk/src/types.ts` — canonical contract
