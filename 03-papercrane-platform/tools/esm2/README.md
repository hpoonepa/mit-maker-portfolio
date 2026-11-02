# ESM-2 — Paper Crane Tool Adapter

ESM-2 (Lin et al., 2023) is the Meta / FAIR protein language model. In the
Paper Crane catalog it is **not a design tool** — it is the canonical
embedding/scoring adapter. Two use cases:

1. **`mode="score"`** — compute a pseudo-log-likelihood (pLL) per sequence,
   used to filter implausible designs *before* sending them to a structure
   predictor (BindCraft / RFdiffusion output → ESM-2 filter → Boltz/Chai).
2. **`mode="embed"`** — extract per-residue (or pooled) hidden states for
   clustering, coverage analysis, and retrieval.

Weights: `facebook/esm2_t33_650M_UR50D` (33 layers, 1280-dim, ~2.6 GB).

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships — same TODO pattern as BindCraft /
ProteinMPNN).

At runtime the container:

1. Reads `/inputs/request.json` (ESM-2 request, `schemas/input.json`).
2. `prepare()` writes `/outputs/workdir/seqs.fasta` from the sequence list.
3. `run()` invokes `python -m papercrane.esm2_runner --fasta ... --mode ... --out /outputs/`.
4. The runner emits either `/outputs/scores.json` **or** `/outputs/embeddings.json` + per-sequence `<id>.npy`.
5. `parse()` normalizes those into `/outputs/result.json` (`schemas/output.json`).

Non-zero exit code signals failure; structured errors are written to
`/outputs/errors.json`.

### Key differences vs design adapters

| | Design adapters (BindCraft, ProteinMPNN, …) | ESM-2 (this adapter) |
|---|---|---|
| Input unit | Targets / backbones | Sequences |
| Output unit | Designed sequences + structures | pLL scores **or** `.npy` embeddings |
| Seeds semantics | Drive sampling | Bookkeeping only (inference is deterministic) |
| `result.json` shape | One record per design | One record per input sequence, discriminated by `mode` |

The `designs` array in `result.json` is a `oneOf` over score-records and
embed-records — see `schemas/output.json`.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, installs `fair-esm==2.0.0` + HuggingFace `transformers`. |
| `manifest.json` | `ToolManifest` catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the normalized ESM-2 request. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json` (discriminated by `mode`). |
| `adapter.py` | `ESM2Adapter` — `prepare` / `run` / `parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU, no weights needed — runner is mocked by fixtures). |

## Weight strategy — Modal volume (default) vs baked image

**Default (production): Modal Volume.** The Dockerfile ships *without* weights
(~2.6 GB saved) and sets `TRANSFORMERS_CACHE=/opt/esm-weights` +
`HF_HOME=/opt/esm-weights`. A Modal Volume is mounted at that path; on first
run the runner downloads the weights; on every subsequent run (across workers
and jobs) the cache hits and startup is instant. This keeps image pulls fast
and amortizes the ~2.6 GB download across the fleet.

**Alternative (air-gapped / offline): bake into the image.** Uncomment the
commented-out `RUN python -c "...AutoModel.from_pretrained..."` block in the
Dockerfile to pre-download weights at build time. Resulting image is ~3.5 GB
instead of ~900 MB but contains no runtime network dependency.

Recommendation: keep the default Modal-volume path. ESM-2 is small enough
that even a first-run cold start is under a minute on A10, and subsequent
warm starts are sub-second. Baking weights in only pays off for offline
deployments.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `mode` | `"score"` | `"score"` → pLL metrics per sequence. `"embed"` → per-residue hidden states persisted as `.npy`. |
| `pool` | `"mean"` | Embedding pooling (embed mode only). `mean` / `cls` → `[1, 1280]`; `none` → `[seq_len, 1280]`. |
| `layer` | `33` | Transformer layer to extract from (embed mode only). `33` is the final layer of `esm2_t33_650M_UR50D`. |

Upstream CLI shape invoked inside the container:

```bash
# mode=score
python -m papercrane.esm2_runner \
  --fasta /inputs/seqs.fasta \
  --mode score \
  --out /outputs/

# mode=embed
python -m papercrane.esm2_runner \
  --fasta /inputs/seqs.fasta \
  --mode embed \
  --pool mean \
  --layer 33 \
  --out /outputs/
```

## Output shapes

**mode=score** — `scores.json` (runner) → `result.json` (adapter):

```jsonc
{
  "designs": [
    {
      "id": "design_0001",
      "seed": 0,
      "mode": "score",
      "sequence": "MKTAY...",
      "metrics": {
        "pll_mean": -1.42,
        "pll_sum":  -46.86,
        "pll_min":  -4.11,
        "ppl":      4.137
      }
    }
  ],
  "runMetadata": {
    "tool": "esm2",
    "mode": "score",
    "model": "esm2_t33_650M_UR50D",
    "adapterVersion": "a1"
  }
}
```

**mode=embed** — `embeddings.json` + `*.npy` (runner) → `result.json` (adapter):

```jsonc
{
  "designs": [
    {
      "id": "design_0001",
      "seed": 0,
      "mode": "embed",
      "embedding_path": "design_0001.npy",
      "shape": [1, 1280],       // or [seq_len, 1280] when pool="none"
      "layer": 33,
      "pool": "mean"
    }
  ],
  "runMetadata": { "tool": "esm2", "mode": "embed", ... }
}
```

The publisher (plan 03, S3 uploader) rewrites each `embedding_path` into an
`artifact_key` pointing at `s3://papercrane-artifacts/<run>/<id>.npy`.

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/esm2/requirements-dev.txt

# Fast unit tests (no weights, no GPU)
pytest tools/esm2

# Full integration (runs the upstream runner — needs the built image + weights)
pytest tools/esm2 -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --output  /outputs
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request
into `/inputs`, mounts the ESM-2 weight volume at `/opt/esm-weights`, launches
the container with the GPU profile declared in `manifest.json` (`A10`, ~1 s/design),
streams stdout to the jobs DB, and on exit rsyncs `/outputs/` to S3. For
`mode=embed`, the `.npy` files are included in the rsync and surfaced as
`artifact_key`s in the published result.

## References

- `docs/plans/02-tool-integration.md` §§4, 6 (catalog row)
- `packages/tools-sdk/src/types.ts` — canonical contract
- Lin et al., "Evolutionary-scale prediction of atomic-level protein structure with a language model" (2023)
