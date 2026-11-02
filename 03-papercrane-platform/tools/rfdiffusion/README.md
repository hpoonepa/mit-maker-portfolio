# RFdiffusion — Paper Crane Tool Adapter

RFdiffusion is a diffusion-based **backbone generator** (Watson et al., Nature
2023; RosettaCommons). It hallucinates binder *backbones* against a target PDB
with optional hotspot residues. It does **not** produce sequences — sequences
come from a downstream ProteinMPNN pass.

## Composition with ProteinMPNN

`manifest.json` declares `"composes": ["proteinmpnn"]`. The Paper Crane
platform's compose helper:

1. Runs this adapter — emits `/outputs/designs/*.pdb` (backbones only).
2. Stages those PDBs into ProteinMPNN's `/inputs/backbones/`.
3. Runs the ProteinMPNN adapter — adds sequences + merges into a unified
   `DesignResult` with both `structurePath` and `sequence`.

The adapter itself is **composition-agnostic**. It never shells out to
ProteinMPNN. If a caller passes `toolParams.skip_mpnn=true`, the platform
skips step 2–3 and the final result contains backbones only.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (normalized `DesignRequest`).
2. Reads `/inputs/target.pdb`.
3. Writes `/outputs/designs/*.pdb` + matching `*.json` metadata (no sequence).
4. Writes `/outputs/result.json` (normalized `DesignResult`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream RFdiffusion at a pinned SHA, fetches weights (or defers to `run.sh`). |
| `manifest.json` | `ToolManifest` — catalog entry. Declares `composes: [proteinmpnn]`. |
| `schemas/input.json` | JSON Schema for RFdiffusion-specific `toolParams`. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json` (backbones, no sequence). |
| `adapter.py` | `RFdiffusionAdapter` — `prepare`/`run`/`parse`. |
| `run.sh` | Container entrypoint; lazy-fetches weights if missing. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/RosettaCommons/RFdiffusion`
- Pinned SHA: `TODO_RFDIFFUSION_SHA` (Dockerfile `ARG RFDIFFUSION_SHA`)
- Weights: `Base_ckpt.pt` from the Baker lab GDrive / HF mirror
  (`ARG RFDIFFUSION_WEIGHTS_URL`). Runtime fallback in `run.sh`.
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7.

To promote a new upstream version, set a commit SHA in CI build args, rebuild,
and bump `adapterVersion` in `manifest.json` if the wrapper changes.

## Invocation

The adapter calls upstream once per seed:

```bash
python /opt/rfdiffusion/scripts/run_inference.py \
  'contigmap.contigs=[A1-150/0 60-150]' \
  'ppi.hotspot_res=[A56,A115]' \
  inference.output_prefix=/outputs/designs/backbone_s0 \
  inference.num_designs=10 \
  inference.input_pdb=/inputs/target.pdb \
  denoiser.noise_scale_ca=1.0 \
  denoiser.noise_scale_frame=1.0 \
  inference.seed=0
```

Outputs: `backbone_s0_0.pdb`, `backbone_s0_1.pdb`, … The adapter writes a
sidecar `*.json` per backbone with `{seed, contigs_used, noise_scale, hotspots}`.

## Advanced contig override

For motif scaffolding or symmetric designs, pass a literal RFdiffusion contig
string via `toolParams.contigs`, e.g. `"[A1-50/10-20/A60-100/0 60-120]"`. When
set, it overrides `target_chain` + `binder_length_range`.

## Running locally (dev loop)

```bash
pip install -r tools/rfdiffusion/requirements-dev.txt
pytest tools/rfdiffusion                 # fast unit tests, no RFdiffusion install
pytest tools/rfdiffusion -m integration  # needs the built image
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request
and target PDB into `/inputs`, launches the container on an A100-40GB
(~35 s/design), streams stdout to the jobs DB, and on exit rsyncs `/outputs/`
to S3. If `manifest.composes` is non-empty and `toolParams.skip_mpnn` is falsy,
the compose helper then runs ProteinMPNN against the emitted backbones and
merges results. The validator image re-scores each *post-MPNN* design with the
canonical Paper Crane metric suite.

## References

- `docs/plans/02-tool-integration.md` §4 (adapter contract), §6 (manifest), §8 (catalog)
- `packages/tools-sdk/src/types.ts` — canonical contract
- Watson et al. (2023). *De novo design of protein structure and function with RFdiffusion.*
