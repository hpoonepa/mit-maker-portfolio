# @papercrane/cli

Developer CLI for Paper Crane. Today it ships one command — `scaffold-tool` —
which creates a new tool adapter skeleton under `tools/<id>/` that passes
`pytest tools/<id>` out of the box.

## Install

From the repo root:

```bash
pnpm install
```

(This package is workspace-local; no publish step is needed.)

## Usage

```bash
pnpm papercrane-cli scaffold-tool <name>
```

`<name>` is the tool id (slug). The CLI validates it against:

- Pattern: `^[a-z][a-z0-9-]{2,30}$`
- Reserved upstream tools: `bindcraft`, `boltz1`, `boltz2`, `chai1`,
  `rfdiffusion`, `proteinmpnn`, `ligandmpnn`, `solublempnn`, `esm2`,
  `boltzgen`, `chroma`, `alphafold3`
- Collision with any existing `tools/<name>/` directory

It then prompts for:

| Field | Notes |
|---|---|
| Display name | Pretty Pascal-case name; default derived from slug |
| Category | `binder_design` / `sequence_design` / `structure_prediction` / `backbone_generation` / `embedding_scoring` |
| Tier | `open` / `open-weights` / `frontier` |
| License | Free text, default `MIT` |
| GPU type | `A10` / `A100-40GB` / `A100-80GB` / `H100` |
| Memory (GB) | Int, default 16 |
| Est seconds/design | Int, default 60 |
| Upstream repo URL | `https://...` |
| Composes | Multi-select from existing tool ids |

…and renders the full scaffold:

```
tools/<id>/
  Dockerfile
  manifest.json
  adapter.py
  run.sh
  README.md
  requirements-dev.txt
  schemas/
    input.json
    output.json
  tests/
    test_adapter.py
    test_manifest.py
    fixtures/
      request.json
      target.pdb
      sample_output/
        design_0001.pdb
        design_0001.json
```

### Next steps

```bash
cd tools/<id>
pip install -r requirements-dev.txt
pytest
docker build .
```

## Development

```bash
pnpm test        # run vitest
pnpm typecheck   # tsc --noEmit
```

The template tree lives under `src/templates/`. Every `*.hbs` file is rendered
with [Handlebars](https://handlebarsjs.com/); non-`.hbs` files (plain PDB
fixtures, `requirements-dev.txt`) are copied verbatim. See `src/generate.ts`
for the walker.
