# benchmark-dispatch composite action

Launches a matrix of Paper Crane benchmark cells on Vast.ai spot A100s and
records each result to the `BenchmarkRun` table. Used by
`benchmark-nightly.yml`, `benchmark-weekly.yml`, `benchmark-on-tool-update.yml`,
and `benchmark-on-target-merge.yml`.

See `docs/plans/04-benchmark-engine.md` §3 for the higher-level design.

## What it does

1. Enumerates all `(tool, target)` cells from the provided globs.
2. Estimates total matrix cost; aborts if it exceeds `max_budget_usd`.
3. Fans out up to `parallelism` concurrent Vast.ai instances (spot A100-80GB),
   each running `seeds_per_cell` seeds for its cell.
4. Per cell: writes a `BenchmarkRun` row (pinned manifest + results digest).
5. Surfaces a structured JSON summary + GH Actions outputs for downstream
   reporting and drift-detection jobs.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `tier` | yes | — | `smoke` \| `full` \| `tool-update` \| `target-merge` |
| `seeds_per_cell` | yes | — | e.g. `10` smoke, `60` full |
| `max_budget_usd` | yes | — | Budget guard; aborts matrix if exceeded |
| `parallelism` | no | `8` | Max concurrent Vast.ai instances |
| `targets_glob` | no | `benchmark/targets/*.yaml` | Glob or comma-separated YAML paths |
| `tools_glob` | no | `tools/*` | Glob of tool directories |
| `tool_version_override` | no | `` | Pins single tool to this version (used by on-tool-update) |
| `trigger_reason` | no | `scheduled` | Freeform audit string |
| `dry_run` | no | `false` | Validate matrix + cost only; no Vast.ai launches |

## Outputs

| Output | Description |
|---|---|
| `run_id` | ULID identifying this orchestration run |
| `summary_json` | Path to the dispatch summary JSON artifact |
| `estimated_cost_usd` | Cost estimate at launch time |
| `cells_total` / `cells_succeeded` / `cells_failed` | Matrix counters |

## Required repo secrets

The calling workflow must pass these in `env:`. The action validates they are
present before launching.

- `VASTAI_API_KEY` — [Vast.ai](https://vast.ai) account API key
- `DATABASE_URL` — Postgres connection string for the `BenchmarkRun` table
- `SLACK_WEBHOOK_URL` *(optional)* — page on budget-abort / dispatch failures
- `GITHUB_TOKEN` — provided automatically by GitHub Actions

## Failure isolation

Individual cell failures do **not** abort sibling cells. A cell can fail and
the matrix continues; the failed cell is recorded in `BenchmarkRun` with
`status = 'failed'` and its error log. The composite step returns
`exit 0` unless:

- budget guard trips (`exit 2`)
- all cells fail (`exit 3`)
- an infrastructure-level error (DB unreachable, Vast.ai auth) occurs (`exit 4`)

## Example usage

```yaml
- name: Run benchmark dispatch
  uses: ./.github/actions/benchmark-dispatch
  with:
    tier: smoke
    seeds_per_cell: 10
    max_budget_usd: 20
    parallelism: 8
  env:
    VASTAI_API_KEY: ${{ secrets.VASTAI_API_KEY }}
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```
