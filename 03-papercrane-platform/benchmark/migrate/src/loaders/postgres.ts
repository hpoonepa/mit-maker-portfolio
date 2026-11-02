/**
 * Postgres loader for benchmark runs + designs.
 *
 * Behavior:
 *   - Creates tables via ddl.sql on first invocation (idempotent).
 *   - Batches inserts in chunks of `BATCH_SIZE` runs, one transaction each.
 *   - Idempotent on `run_id`: `INSERT ... ON CONFLICT (run_id) DO NOTHING`.
 *     Runs that are skipped by this clause do NOT have their designs
 *     re-inserted — we assume (run_id, seed) is already consistent.
 *   - Returns counts of inserted vs skipped so the CLI summary is accurate.
 */

import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { BenchmarkRun } from "../schema.js";

export const BATCH_SIZE = 100;

export interface LoadResult {
  runs_inserted: number;
  runs_skipped: number;
  designs_inserted: number;
}

/** Minimal query result shape consumed by the loader. */
export interface PgQueryResult<T = Record<string, unknown>> {
  rows: T[];
  rowCount: number | null;
}

/** Narrow client interface — subset of `pg.PoolClient` we depend on. */
export interface PgClient {
  query<T = Record<string, unknown>>(
    sql: string,
    params?: unknown[],
  ): Promise<PgQueryResult<T>>;
  release(): void;
}

/** Narrow pool interface — subset of `pg.Pool` we depend on. */
export interface LoaderLike {
  query(sql: string, params?: unknown[]): Promise<PgQueryResult>;
  connect(): Promise<PgClient>;
  end?(): Promise<void>;
}

const here = dirname(fileURLToPath(import.meta.url));
const DDL_PATH = join(here, "ddl.sql");

/** Run the DDL script. Safe to call on every startup. */
export async function ensureSchema(pool: LoaderLike): Promise<void> {
  const ddl = await readFile(DDL_PATH, "utf8");
  await pool.query(ddl);
}

/**
 * Insert a list of runs + their designs.
 *
 * Runs are processed in batches of BATCH_SIZE. Each batch runs in one
 * transaction: if any query inside the batch fails the whole batch is
 * rolled back and the error is re-thrown.
 *
 * Idempotency contract: ON CONFLICT (run_id) DO NOTHING. When a run is
 * skipped, its designs are NOT inserted (the run already exists so its
 * designs are assumed to already exist).
 */
export async function loadRuns(
  pool: LoaderLike,
  runs: BenchmarkRun[],
): Promise<LoadResult> {
  let runs_inserted = 0;
  let runs_skipped = 0;
  let designs_inserted = 0;

  for (let i = 0; i < runs.length; i += BATCH_SIZE) {
    const batch = runs.slice(i, i + BATCH_SIZE);
    const client: PgClient = await pool.connect();
    try {
      await client.query("BEGIN");
      for (const run of batch) {
        const inserted = await insertRun(client, run);
        if (inserted) {
          runs_inserted += 1;
          designs_inserted += await insertDesigns(client, run);
        } else {
          runs_skipped += 1;
        }
      }
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw err;
    } finally {
      client.release();
    }
  }

  return { runs_inserted, runs_skipped, designs_inserted };
}

/** Returns true if the row was inserted, false if ON CONFLICT skipped it. */
async function insertRun(client: PgClient, run: BenchmarkRun): Promise<boolean> {
  const sql = `
    INSERT INTO benchmark_runs (
      run_id, target_id, tool_id, tool_version, config_hash,
      seed_start, seed_end, compute_env_hash,
      cost_usd, wallclock_sec, results_digest,
      source, git_sha, notes
    ) VALUES (
      $1, $2, $3, $4, $5,
      $6, $7, $8,
      $9, $10, $11,
      $12, $13, $14
    )
    ON CONFLICT (run_id) DO NOTHING
    RETURNING run_id
  `;
  const params = [
    run.run_id,
    run.target_id,
    run.tool_id,
    run.tool_version,
    stripHashPrefix(run.config_hash),
    run.seed_range[0],
    run.seed_range[1],
    stripHashPrefix(run.compute_env_hash),
    run.cost_usd,
    run.wallclock_sec,
    stripHashPrefix(run.results_digest),
    run.source,
    run.git_sha ?? null,
    run.notes ?? null,
  ];
  const res = await client.query<{ run_id: string }>(sql, params);
  return res.rowCount !== null && res.rowCount > 0;
}

/**
 * Bulk-insert all designs for a run using a single multi-row INSERT. Uses
 * ON CONFLICT (run_id, seed) DO NOTHING as a belt-and-braces guard against
 * half-loaded runs (shouldn't happen because the parent was just inserted
 * inside the same transaction).
 */
async function insertDesigns(
  client: PgClient,
  run: BenchmarkRun,
): Promise<number> {
  if (run.designs.length === 0) return 0;
  const cols = ["run_id", "seed", "sequence", "structure_path", "rank", "metrics"];
  const placeholders: string[] = [];
  const params: unknown[] = [];
  run.designs.forEach((d, i) => {
    const base = i * cols.length;
    placeholders.push(
      `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, $${base + 6}::jsonb)`,
    );
    params.push(
      run.run_id,
      d.seed,
      d.sequence,
      d.structurePath,
      d.rank ?? null,
      JSON.stringify(d.metrics ?? {}),
    );
  });
  const sql = `
    INSERT INTO designs (run_id, seed, sequence, structure_path, rank, metrics)
    VALUES ${placeholders.join(", ")}
    ON CONFLICT (run_id, seed) DO NOTHING
  `;
  const res = await client.query(sql, params);
  return res.rowCount ?? 0;
}

function stripHashPrefix(hash: string): string {
  return hash.replace(/^sha256:/i, "").toLowerCase();
}
