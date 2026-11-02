# scripts/benchmark

Standalone CLIs invoked by the continuous-benchmark GitHub Actions workflows.
Kept **outside** the pnpm workspace on purpose so that CI installs are minimal
(no need to hydrate the whole monorepo just to dispatch a Vast.ai run).

| Script | Invoked by | Purpose |
|---|---|---|
| `dispatch.ts` | `.github/actions/benchmark-dispatch` | Enumerates `(tool × target)` matrix, enforces budget guard, fans out to Vast.ai spot A100s, records each cell to `BenchmarkRun`, emits structured JSON summary |
| `report-results.ts` | workflow `finalize` job | Reads results from Postgres, posts a summary as a GitHub commit comment + Slack message |
| `drift-detect.ts` | workflow `finalize` job | Computes 4-week trailing mean/stdev per (tool, target); if latest weekly >2σ, opens a `benchmark-incident` GitHub issue + pages Slack |

See `docs/plans/04-benchmark-engine.md` §3 for the design.

## Install (CI only)

```bash
cd scripts/benchmark
npm install --no-audit --no-fund
```

This directory has its own `package.json` and is intentionally *not* in
`pnpm-workspace.yaml`.

## Run locally

```bash
# Dry-run the nightly matrix without launching Vast.ai
DATABASE_URL=postgres://... VASTAI_API_KEY=... \
  npx tsx dispatch.ts \
    --tier smoke --seeds 10 --max-budget 20 \
    --parallelism 8 \
    --targets 'benchmark/targets/*.yaml' \
    --tools 'tools/*' \
    --dry-run true

# Post a summary comment for an existing run
GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo GITHUB_SHA=$(git rev-parse HEAD) \
DATABASE_URL=... \
  npx tsx report-results.ts --tier smoke --run-id 01HXXXX...

# Check drift across all tool/target pairs
DATABASE_URL=... GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo \
  npx tsx drift-detect.ts --tier full --z-threshold 2
```

## Tests

```bash
npm test           # vitest run
npm run test:watch # watch mode
npm run typecheck  # tsc --noEmit
```

`drift-detect.test.ts` tests the pure helpers (`mean`, `stdev`, `zScore`,
`detectDrift`) against a fixture time-series — no DB required.

## Required GitHub repo secrets

Used by the four workflows that call these scripts:

| Secret | Required? | Used by | Notes |
|---|---|---|---|
| `VASTAI_API_KEY` | **required** | `dispatch.ts` | Account API key from vast.ai |
| `DATABASE_URL` | **required** | all three | Postgres connection string — must have write access to `BenchmarkRun` |
| `SLACK_WEBHOOK_URL` | optional | `dispatch.ts`, `report-results.ts`, `drift-detect.ts` | If unset, Slack pages are skipped silently |
| `ZENODO_TOKEN` | optional | `report-results.ts --publish-zenodo` | Only needed when the weekly workflow is dispatched with `publish=true` |
| `GITHUB_TOKEN` | auto | all three | Provided by GitHub Actions; needs `issues: write` + `pull-requests: write` for commit comments and incident issues |

## Workflow index

| Workflow | Trigger | Tier | Seeds | Budget |
|---|---|---|---|---|
| `benchmark-nightly.yml` | cron `0 2 * * *` + manual | smoke | 10 | $20 |
| `benchmark-weekly.yml` | cron `0 4 * * 0` + manual | full | 60 | $500 |
| `benchmark-on-tool-update.yml` | manual w/ `tool`+`version` | single-tool | 30 | $150 |
| `benchmark-on-target-merge.yml` | push on `benchmark/targets/*.yaml` | full | 60 | $200 |

## Exit codes (`dispatch.ts`)

| Code | Meaning |
|---|---|
| 0 | Matrix completed (individual cell failures are isolated) |
| 2 | Budget guard tripped — aborted before launching any instance |
| 3 | All cells failed |
| 4 | Infrastructure error (DB / Vast.ai auth) |
| 5 | CLI validation error |
