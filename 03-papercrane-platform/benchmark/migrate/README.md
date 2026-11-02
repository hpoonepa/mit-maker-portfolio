# @papercrane/benchmark-migrate

CLI for porting historical Paper Crane campaign results (God V3B, 5G51 V4,
RBX1) into the normalized Postgres schema that powers the public leaderboard
at `/leaderboard`.

This is Milestone **M1** of the benchmark engine plan
(`docs/plans/04-benchmark-engine.md` §11). Once every historical run is in
Postgres, the static JSON on `papercrane-h2im.vercel.app` can be retired.

---

## Usage

```bash
# Parse + validate only, do not write.
pnpm --filter @papercrane/benchmark-migrate migrate \
  --source god-v3b \
  --input ./path/to/god-v3b-results \
  --dry-run

# Load into Postgres. DATABASE_URL must be set OR --database-url passed.
DATABASE_URL=postgres://... pnpm --filter @papercrane/benchmark-migrate migrate \
  --source 5g51-v4 \
  --input ./path/to/5g51-v4-results

# Load every campaign in one shot.
pnpm --filter @papercrane/benchmark-migrate migrate \
  --source all \
  --input ./path/to/all-campaigns
```

### Flags

| Flag             | Required | Default | Description                                    |
|------------------|----------|---------|------------------------------------------------|
| `--source <id>`  | yes      | —       | `god-v3b`, `5g51-v4`, `rbx1`, or `all`          |
| `--input <path>` | yes      | —       | Directory to recursively walk for `*.json`      |
| `--dry-run`      | no       | `false` | Parse + validate only; skip database writes     |
| `--database-url` | no       | env     | Override `DATABASE_URL` (ignored in dry-run)    |

### Output

The CLI emits a single JSON summary to stdout:

```json
{
  "runs_parsed": 42,
  "runs_inserted": 40,
  "runs_skipped": 2,
  "designs_inserted": 2400,
  "errors": [],
  "dry_run": false
}
```

Exit code is `1` if any fatal error is thrown (invalid source id, missing
`DATABASE_URL`, DB connection failure, unparseable JSON).

---

## Schema

The loader creates two tables on first invocation (DDL in
`src/loaders/ddl.sql`):

- `benchmark_runs` — one row per `(target, tool, config, seed_range)` run.
  `run_id` is the primary key; inserts are idempotent via
  `ON CONFLICT (run_id) DO NOTHING`.
- `designs` — one row per predicted binder. `(run_id, seed)` is unique.
  Metrics live in a `JSONB` column with a GIN index for flexible queries.

Zod schemas in `src/schema.ts` define the in-memory representation:

- `DesignResult` — one predicted binder (seed, sequence, structure path, metrics)
- `BenchmarkRun` — one run: target/tool/config + all its designs + hashes + cost
- `BenchmarkCell` — aggregated leaderboard cell (populated by the API layer, not this tool)
- `RunManifest` — full reproducibility manifest (superset of `BenchmarkRun`)

---

## Reproducibility hashes

Three SHA-256 fingerprints are computed per run and stored in
`benchmark_runs`. They match the definitions in
`benchmark/methodology-v1.0.md` §4:

1. **Input fingerprint** — `sha256(pdb_bytes || chain || sorted(hotspots) || version)`
2. **Config hash** — `sha256(canonical_json(config))`
3. **Compute env hash** — `sha256(canonical_json({gpu, driver, cuda, container_digest, provider}))`

A fourth hash — **results digest** — is computed over the sorted
`(seed, sequence, metrics)` tuples. The re-run verifier on the leaderboard
uses this to detect drift.

Helpers live in `src/hashing.ts`. Canonical JSON is produced by deep-sorting
object keys before `JSON.stringify` so two semantically-equal configs
always hash to the same digest.

---

## Adding a new source parser

1. Create `src/parsers/<source-id>.ts`:

   ```ts
   import type { BenchmarkRun } from "../schema.js";
   import { parseCampaignDir } from "./util.js";

   export const sourceId = "my-campaign" as const;

   export async function parse(inputDir: string): Promise<BenchmarkRun[]> {
     return parseCampaignDir({
       inputDir,
       sourceId,
       campaignMatch: (raw) => raw.campaign.toLowerCase() === "my-campaign",
     });
   }

   export default { sourceId, parse };
   ```

2. Register the new id in `src/schema.ts` — add it to the `source` enum on
   `BenchmarkRunSchema`.

3. Register the parser in `src/parsers/index.ts`:

   ```ts
   import myCampaign from "./my-campaign.js";
   const registry = {
     ...,
     "my-campaign": myCampaign,
   };
   ```

   Also add the id to the exported `ALL_SOURCES` array.

4. Add a fixture under `tests/fixtures/my-campaign-sample/run-1.json` and a
   test under `tests/parsers/`. The raw JSON shape is defined in
   `src/parsers/util.ts` (`RawCampaignRunSchema`) — all existing parsers
   share it.

---

## Running tests

```bash
pnpm --filter @papercrane/benchmark-migrate install
pnpm --filter @papercrane/benchmark-migrate test
```

Tests cover:

- `tests/schema.test.ts` — zod schema happy-path + rejection cases
- `tests/parsers/god-v3b.test.ts` — fixture parsing, determinism, cross-campaign filtering
- `tests/loader.test.ts` — batched INSERTs, `ON CONFLICT DO NOTHING`, rollback on failure

The loader test mocks `pg.Pool` via `vi.fn` — no live database required.

---

## Known gaps

- **Real on-disk layout**: the parsers accept the fixture shape defined in
  `src/parsers/util.ts`. Once the concrete paths under
  `/Users/harsha/Desktop/claudeprojects/mosaic/` are mapped, each parser's
  `campaignMatch` predicate (and possibly its `inputDir` walker) may need
  an adapter pass.
- **Workspace registration**: this package is standalone. Add
  `benchmark/migrate` to `pnpm-workspace.yaml`'s `packages:` list to enable
  `pnpm --filter @papercrane/benchmark-migrate`.
- **Manifest loader**: `RunManifest` is defined but not yet persisted —
  that is M2 work (IPFS + S3 pinning).
