# LigandMPNN — Paper Crane Tool Adapter

LigandMPNN (Dauparas et al., 2023) extends ProteinMPNN with explicit
small-molecule context: residues within `ligand_context_radius` Å of a ligand
heavy atom are decoded with ligand-aware embeddings, making this the right tool
for active-site and cofactor-pocket sequence design. In the Paper Crane catalog
it sits alongside ProteinMPNN and SolubleMPNN as the ligand-aware branch of
MPNN-family sequence design — see `docs/plans/02-tool-integration.md` §8.

## Contract

Paper Crane tools implement the `ToolAdapter` contract from
`packages/tools-sdk` (TypeScript spec; Python mirror stubbed inline in
`adapter.py` until the Python SDK ships — same TODO pattern as ProteinMPNN).

At runtime the container:

1. Reads `/inputs/request.json` (LigandMPNN request, `schemas/input.json`).
2. Reads `/inputs/backbones/*.pdb` (one or more backbones staged by the scheduler).
3. Reads `/inputs/ligands/ligand.sdf` if `ligand_sdf` was provided, OR
   materialises `ligand_atoms` into a HETATM-only `ligand.pdb` in the workdir.
4. Writes `/outputs/designs/*.fasta` + matching `*.json` metrics (one per design).
5. Writes `/outputs/result.json` (normalized `DesignResult`, `schemas/output.json`).

Non-zero exit code signals failure; structured errors are appended to
`/outputs/errors.json`.

### Input shape vs ProteinMPNN

Where ProteinMPNN takes `{ backbones, seeds, params }`, LigandMPNN additionally
accepts **one** of:

- `ligand_atoms: [{ residueId, atomName, x, y, z, element }, ...]` — inline
  per-atom coordinates; materialised to a HETATM-only PDB at prepare time.
- `ligand_sdf: "s3://..."` — S3 URI to an SDF/MOL file, resolved into
  `/inputs/ligands/ligand.sdf` by the scheduler.

The two are mutually exclusive; `validate()` rejects requests that set both.
This is the main deviation from `tools/proteinmpnn/` and is reflected in the
schemas, fixtures, and the additional `--ligands` entrypoint flag.

## Layout

| File | Purpose |
|---|---|
| `Dockerfile` | Builds on `ghcr.io/papercrane/base-cuda12:latest`, clones upstream LigandMPNN at a pinned SHA. |
| `manifest.json` | `ToolManifest` catalog entry. See `packages/tools-sdk/src/types.ts`. |
| `schemas/input.json` | JSON Schema for the normalized LigandMPNN request. |
| `schemas/output.json` | JSON Schema for `/outputs/result.json`. |
| `adapter.py` | `LigandMPNNAdapter` — `prepare` / `run` / `parse`. |
| `run.sh` | Container entrypoint. |
| `tests/` | `pytest` suite (no GPU needed). |

## Upstream

- Source: `https://github.com/dauparas/LigandMPNN`
- Pinned SHA: `TODO_LIGANDMPNN_SHA` (Dockerfile `ARG LIGANDMPNN_SHA`)
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
| `ligand_context_radius` | `8.0` | Å cutoff around ligand atoms for ligand-conditioned decoding. |
| `fixed_positions` | `null` | Optional `{ chain: [resi, ...] }` map of positions to keep fixed. |

Upstream CLI shape invoked inside the container:

```bash
python /opt/ligandmpnn/run.py \
  --pdb_path <backbones-dir> \
  --ligand_pdb <ligand.sdf | ligand.pdb> \
  --out_folder <outputs-dir> \
  --num_seq_per_target <N> \
  --sampling_temp <T> \
  --omit_AAs <omit_aas> \
  --ligand_context_radius <R> \
  --seed <seed>
```

## Running locally (dev loop)

```bash
# Install test deps
pip install -r tools/ligandmpnn/requirements-dev.txt

# Fast unit tests (no LigandMPNN install required)
pytest tools/ligandmpnn

# Full integration (runs the upstream CLI — needs the built image)
pytest tools/ligandmpnn -m integration
```

Inside the container the entrypoint invokes:

```bash
python /opt/papercrane/adapter.py \
  --request    /inputs/request.json \
  --backbones  /inputs/backbones \
  --ligands    /inputs/ligands \
  --output     /outputs
```

## How Paper Crane runs this adapter

The job scheduler (plan 03) pulls the pinned image digest, stages the request,
backbone PDBs, and ligand file (if any) into `/inputs`, launches the container
with the GPU profile declared in `manifest.json` (`A10`, ~6 s/design), streams
stdout to the jobs DB, and on exit rsyncs `/outputs/` to S3. The validator
image then re-scores each design with the canonical Paper Crane metric suite —
LigandMPNN's native `score`, `confidence_mean`, and `ligand_context_residues`
remain alongside for users who want the raw numbers.

## References

- `docs/plans/02-tool-integration.md` §§4, 6, 8 (catalog row)
- `packages/tools-sdk/src/types.ts` — canonical contract
- `tools/proteinmpnn/` — base-MPNN sibling adapter this one extends
