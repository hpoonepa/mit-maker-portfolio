# Chroma — Paper Crane Tool Adapter

Chroma (Ingraham et al., *Nature* 2023; Generate Biomedicines) is a
**programmable generative model** for protein structure. It produces backbones
via a graph-based diffusion sampler steered by composable *conditioners*
(substructure, symmetry, shape, classifier-guided, subsequence, …). Chroma does
**not** produce sequences — sequences come from a downstream ProteinMPNN pass.

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

## Unconditional generation

Chroma supports pure de novo generation — no target, no substructure
conditioner. When `targetPdb` is omitted from the request **and** no
`SubstructureConditioner` is present, the adapter runs in unconditional mode
and `runMetadata.unconditional` is set to `true`. `run.sh` conditionally passes
`--target` based on whether `/inputs/target.pdb` exists.

## Conditioners

Chroma's programmability is its headline feature. The input schema exposes:

```json
"conditioners": [
  { "type": "SubstructureConditioner", "params": { "motif_pdb": "...", "motif_chain": "A" } },
  { "type": "SymmetryConditioner",     "params": { "symmetry": "C3" } },
  { "type": "ShapeConditioner",        "params": { "shape": "toroidal" } },
  { "type": "ProClassConditioner",     "params": { "class": "immunoglobulin" } }
]
```

The adapter forwards `conditioners[]` to the upstream Python CLI verbatim
(`python -m chroma.cli --config <cfg.json>`). The CLI is responsible for
instantiating the matching classes from `chroma.layers.structure.conditioners`.

**Validation rule:** a `SubstructureConditioner` requires `targetPdb` at the
request level — otherwise `validate()` returns a structured error.

**Open question:** the full conditioner type union is intentionally
open-ended. The schema carries a `TODO` comment to tighten to a closed enum
once upstream locks its public API.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships).

At runtime the container:

1. Reads `/inputs/request.json` (normalized `DesignRequest`).
2. Reads `/inputs/target.pdb` **if present** (optional for Chroma).
3. Writes `/outputs/designs/*.pdb` + matching `*.json` metadata (no sequence).
4. Writes `/outputs/result.json` (normalized `DesignResult`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream Chroma at a pinned SHA, installs `generate-chroma`, fetches weights (or defers to `run.sh`). |
| `manifest.json` | `ToolManifest` — catalog entry. Declares `composes: [proteinmpnn]`. |
| `schemas/input.json` | JSON Schema for Chroma-specific `toolParams`, including the open-ended `conditioners[]` union. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json` (backbones, no sequence). |
| `adapter.py` | `ChromaAdapter` — `prepare`/`run`/`parse`. |
| `run.sh` | Container entrypoint; lazy-fetches weights if missing; passes `--target` only when a target PDB is staged. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/generatebio/chroma`
- Pinned SHA: `TODO_CHROMA_SHA` (Dockerfile `ARG CHROMA_SHA`)
- pip package: `generate-chroma==1.0.0`
- Weights: `chroma_backbone.pt` (Generate Biomedicines HF mirror, Apache-2.0).
  `ARG CHROMA_WEIGHTS_URL`. Runtime fallback in `run.sh`.
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7.

To promote a new upstream version, set a commit SHA + pip version in CI build
args, rebuild, and bump `adapterVersion` in `manifest.json` if the wrapper
changes.

## Invocation

The adapter calls upstream once per seed:

```bash
python -m chroma.cli \
  --config /outputs/workdir/chroma.json \
  --out   /outputs/designs/design_s0 \
  --seed  0
```

Outputs: `design_s0_0000.pdb`, `design_s0_0001.pdb`, … The adapter writes a
sidecar `*.json` per backbone with `{seed, temperature, steps,
conditioners_applied, length_target, unconditional}`.

## Running locally (dev loop)

```bash
pip install -r tools/chroma/requirements-dev.txt
pytest tools/chroma                 # fast unit tests, no Chroma install
pytest tools/chroma -m integration  # needs the built image
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request
(and optional target PDB) into `/inputs`, launches the container on an
A100-40GB (~50 s/design), streams stdout to the jobs DB, and on exit rsyncs
`/outputs/` to S3. If `manifest.composes` is non-empty and
`toolParams.skip_mpnn` is falsy, the compose helper then runs ProteinMPNN
against the emitted backbones and merges results. The validator image
re-scores each *post-MPNN* design with the canonical Paper Crane metric suite.

## References

- `docs/plans/02-tool-integration.md` §4 (adapter contract), §6 (manifest), §8 (catalog)
- `packages/tools-sdk/src/types.ts` — canonical contract
- Ingraham, Baranov, Costello et al. (2023). *Illuminating protein space with a programmable generative model.* Nature.
