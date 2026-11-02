# SolubleMPNN — Paper Crane Tool Adapter

SolubleMPNN (Dauparas et al., 2022) is ProteinMPNN loaded with the
soluble-biased checkpoint `soluble_v_48_020.pt`. It designs sequences for a
fixed backbone via inverse folding, biased toward residues that favour soluble
E. coli expression. In the Paper Crane catalog it is the go-to sequence-design
tool for any design that needs to express and stay out of inclusion bodies —
see `docs/plans/02-tool-integration.md` §8.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships — same TODO pattern as ProteinMPNN).

At runtime the container:

1. Reads `/inputs/request.json` (SolubleMPNN request, `schemas/input.json`).
2. Reads `/inputs/backbones/*.pdb` (one or more backbones staged by the scheduler).
3. Writes `/outputs/designs/*.fasta` + matching `*.json` metrics (one per design).
4. Writes `/outputs/result.json` (normalized `DesignResult`, `schemas/output.json`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

### Difference vs ProteinMPNN

Mechanically identical to `tools/proteinmpnn/`. The only functional deltas are:

- The adapter hard-pins `--model_name soluble_v_48_020.pt` — callers cannot
  override the checkpoint. This is the whole point of the tool.
- `omit_aas` defaults to `"CXHKR"` (vs ProteinMPNN's `"CX"`) to remove the
  residues most associated with aggregation and poor E. coli expression:
  cysteine (disulfide mischief), the non-standard `X`, and the polybasic
  triad H/K/R.
- A new enum param `solubility_strictness` (see below) clamps temperature and
  the omit list in `strict` mode for high-stakes expression campaigns.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream ProteinMPNN at a pinned SHA, selects the soluble checkpoint at runtime. |
| `manifest.json` | `ToolManifest` catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the normalized SolubleMPNN request. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `SolubleMPNNAdapter` — `prepare` / `run` / `parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/dauparas/ProteinMPNN` (same repo as ProteinMPNN —
  the soluble weights live under `soluble_model_weights/` inside it).
- Checkpoint: `soluble_v_48_020.pt` (module constant `SOLUBLE_MODEL_NAME` in
  `adapter.py`).
- Pinned SHA: `TODO_PROTEINMPNN_SHA` (Dockerfile `ARG PROTEINMPNN_SHA`) — kept
  in lock-step with `tools/proteinmpnn/` so both tools inherit the same
  upstream bugfixes.
- **Not** vendored as a git submodule — cloned at image build time per plan
  02 §7.

To promote a new upstream version, update the build arg in CI, rebuild both
`proteinmpnn` and `solublempnn` images, and bump `adapterVersion` in
`manifest.json` if the wrapper changes.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `temperature` | `0.1` | Sampling temperature; lower = more deterministic. Clamped to `≤ 0.1` in strict mode. |
| `omit_aas` | `"CXHKR"` | AAs to exclude. Default drops cysteines, the non-standard `X`, and H/K/R to reduce polybasic-cluster aggregation and deamidation risk. |
| `num_seq_per_target` | `1` | Sequences per backbone per seed. |
| `solubility_strictness` | `"default"` | `"default"` honours the caller's `temperature` + `omit_aas`. `"strict"` clamps temperature to ≤ 0.1 and forces `omit_aas` to a superset of `"CXHKR"` — use for campaigns where expression yield trumps diversity. |
| `fixed_positions` | `null` | Optional `{ chain: [resi, ...] }` map of positions to keep fixed. |

Upstream CLI shape invoked inside the container (note the pinned model name):

```bash
python /opt/proteinmpnn/protein_mpnn_run.py \
  --pdb_path    <backbones-dir> \
  --out_folder  <outputs-dir> \
  --model_name  soluble_v_48_020.pt \
  --num_seq_per_target <N> \
  --sampling_temp <T> \
  --omit_AAs   <omit_aas> \
  --seed <seed>
```

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/solublempnn/requirements-dev.txt

# Fast unit tests (no ProteinMPNN install required)
pytest tools/solublempnn

# Full integration (runs the upstream CLI with the soluble checkpoint —
# needs the built image)
pytest tools/solublempnn -m integration
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
declared in `manifest.json` (`A10`, ~5 s/design), streams stdout to the jobs
DB, and on exit rsyncs `/outputs/` to S3. The validator image then re-scores
each design with the canonical Paper Crane metric suite — SolubleMPNN's native
`score` and `confidence_mean` remain alongside for users who want the raw
numbers.

## When to pick SolubleMPNN over ProteinMPNN

- The design is destined for E. coli expression and you want to minimize
  inclusion-body risk without a redesign loop.
- You're optimising an existing hit for higher yield / lower aggregation.
- You're running a secreted-protein campaign where cysteine scrambling would
  ruin the disulfide pattern.

Prefer vanilla ProteinMPNN when you need maximal sequence diversity, are
designing for a non-E. coli host (yeast, mammalian), or when cysteines /
polybasic residues are load-bearing for function (e.g. zinc fingers, DNA
binders).

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 8 (catalog row)
- `packages/tools-sdk/src/types.ts` — canonical contract
- Dauparas et al., *Science* 2022 — ProteinMPNN + soluble variant
