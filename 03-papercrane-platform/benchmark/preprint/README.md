# Paper Crane Benchmark — Preprint

Source for the continuously updated Paper Crane benchmark preprint. This
package is rebuilt on a monthly cadence by GitHub Actions and archived to
Zenodo with a citable DOI.

## Contents

| Path | Purpose |
|------|---------|
| `paper.tex` | LaTeX source for the preprint |
| `references.bib` | BibTeX references (natbib / `unsrtnat`) |
| `generate-assets.ts` | Pulls live leaderboard data and emits `figures/` + `tables/` + `data/` |
| `Makefile` | Build, clean, assets, and package targets |
| `data/`, `figures/`, `tables/` | Generated per build (do not edit by hand) |
| `tests/` | Vitest suite for the asset generator |

## Prerequisites

- **Node.js** 20+ and **pnpm** (for `generate-assets.ts` and the repo workspace)
- **texlive-full** (or at minimum: `pdflatex`, `bibtex`, `natbib`, `booktabs`,
  `graphicx`, `hyperref`, `geometry`)
- **zip** (for `make package`)
- Optional: `DATABASE_URL` pointing at the Paper Crane leaderboard Postgres
  instance if you want to regenerate assets from live data. Without it,
  `generate-assets.ts` falls back to the checked-in snapshot.

On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y texlive-full zip
corepack enable
```

## Build Locally

From the repo root:

```bash
# install workspace deps (first time only)
pnpm install

# regenerate figures + tables + data snapshot
pnpm --filter @papercrane/preprint-assets run build:assets

# compile the PDF
make -C benchmark/preprint build

# produce a versioned release zip
make -C benchmark/preprint package VERSION=2026.04
```

Artifacts:

- `benchmark/preprint/paper.pdf`
- `benchmark/preprint/benchmark-v<VERSION>-<DATE>.zip`

## How CI Publishes Monthly

The workflow at `.github/workflows/preprint-publish.yml` runs on the first of
each month at 08:00 UTC (and can be invoked manually via
`workflow_dispatch`). It:

1. Checks out the repo and sets up Node 20 + pnpm.
2. Installs workspace dependencies with a frozen lockfile.
3. Installs `texlive-full` and `zip` via `apt`.
4. Runs `pnpm --filter @papercrane/preprint-assets run build:assets` to
   regenerate `figures/`, `tables/`, and `data/` from the live leaderboard
   (requires the `DATABASE_URL` secret; falls back to snapshot otherwise).
5. Runs `make -C benchmark/preprint build` then
   `make -C benchmark/preprint package` to produce the versioned zip.
6. Uploads the zip as a workflow artifact.
7. If the `ZENODO_TOKEN` secret is configured, publishes a new Zenodo
   deposition and captures the resulting DOI.
8. Opens a pull request that bumps the DOI and version in `CITATION.cff`.

### Required / optional secrets

- `ZENODO_TOKEN` **(required for DOI publishing)** — personal access token
  from <https://zenodo.org/account/settings/applications/tokens/new/> with the
  `deposit:write` and `deposit:actions` scopes.
- `DATABASE_URL` *(optional)* — Postgres connection string for the live
  leaderboard. If absent, the asset generator uses the checked-in snapshot in
  `data/leaderboard-snapshot.json`.

## Bumping the Version

Edit `CITATION.cff` at the repo root and update:

```yaml
version: 2026.04
date-released: 2026-04-01
doi: 10.5281/zenodo.XXXXXXX
```

The CI workflow updates the DOI automatically when it receives a new Zenodo
record; you only need to hand-edit the version and date for an out-of-band
release. Commit the change on a feature branch and open a PR — the
`preprint-publish` workflow also opens its own PR when it runs on cron.
