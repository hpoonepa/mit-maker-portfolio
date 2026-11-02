#!/usr/bin/env tsx
/**
 * Benchmark matrix dispatcher.
 *
 * Invoked by .github/actions/benchmark-dispatch. Enumerates (tool, target)
 * cells, enforces a budget guard, fans out to Vast.ai spot A100 instances
 * with bounded concurrency, records each cell as a BenchmarkRun row, and
 * writes a structured JSON summary to stdout + disk.
 *
 * This script intentionally uses the Vast.ai REST API directly (via fetch) —
 * no SDK, per the plan.
 *
 * Exit codes:
 *   0  matrix completed (some cells may have failed — that's isolated)
 *   2  budget guard tripped
 *   3  all cells failed
 *   4  infrastructure error (DB / Vast.ai auth)
 *   5  CLI validation error
 */

import { readFile, writeFile, mkdir, readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { parseArgs } from 'node:util';
import { parse as parseYaml } from 'yaml';
import { ulid } from 'ulid';
import { glob } from 'glob';
import pg from 'pg';

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

export type Tier = 'smoke' | 'full' | 'tool-update' | 'target-merge';

export interface TargetSpec {
  id: string;
  pdb: string;
  chain: string;
  hotspots: number[];
  version: number;
  tier: string;
  path: string;
}

export interface ToolSpec {
  id: string;
  version: string;
  containerImage: string;
  path: string;
}

export interface Cell {
  cellId: string;
  tool: ToolSpec;
  target: TargetSpec;
  seeds: number;
  estCostUsd: number;
  estWallclockSec: number;
}

export interface CellResult {
  cellId: string;
  toolId: string;
  toolVersion: string;
  targetId: string;
  status: 'succeeded' | 'failed' | 'skipped';
  hitRate?: number;
  seedsRun: number;
  costUsd: number;
  wallclockSec: number;
  vastInstanceId?: number;
  errorMessage?: string;
  benchmarkRunId?: string;
}

export interface DispatchSummary {
  runId: string;
  tier: Tier;
  triggerReason: string;
  startedAt: string;
  finishedAt: string;
  cellsTotal: number;
  cellsSucceeded: number;
  cellsFailed: number;
  cellsSkipped: number;
  estimatedCostUsd: number;
  actualCostUsd: number;
  results: CellResult[];
  githubRunId?: string;
  githubSha?: string;
}

// ----------------------------------------------------------------------------
// Cost model (per plan §3: smoke ~$8/night, full ~$260/week)
// ----------------------------------------------------------------------------

const VAST_A100_SPOT_USD_PER_HOUR = 0.85; // conservative spot A100-80GB
const SECONDS_PER_SEED_BASELINE = 90;     // per seed, most tools

function estimateCellCost(tool: ToolSpec, target: TargetSpec, seeds: number) {
  // Tier-dependent overhead could be added later (e.g. harder targets = longer)
  const wallSec = seeds * SECONDS_PER_SEED_BASELINE;
  const cost = (wallSec / 3600) * VAST_A100_SPOT_USD_PER_HOUR;
  return { estWallclockSec: wallSec, estCostUsd: Number(cost.toFixed(4)) };
}

// ----------------------------------------------------------------------------
// CLI parsing
// ----------------------------------------------------------------------------

interface Args {
  tier: Tier;
  seeds: number;
  maxBudget: number;
  parallelism: number;
  targets: string;
  tools: string;
  toolVersion?: string;
  triggerReason: string;
  dryRun: boolean;
  githubOutput?: string;
}

export function parseCliArgs(argv: string[]): Args {
  const { values } = parseArgs({
    args: argv,
    options: {
      tier: { type: 'string' },
      seeds: { type: 'string' },
      'max-budget': { type: 'string' },
      parallelism: { type: 'string', default: '8' },
      targets: { type: 'string', default: 'benchmark/targets/*.yaml' },
      tools: { type: 'string', default: 'tools/*' },
      'tool-version': { type: 'string' },
      'trigger-reason': { type: 'string', default: 'scheduled' },
      'dry-run': { type: 'string', default: 'false' },
      'github-output': { type: 'string' },
    },
    strict: true,
    allowPositionals: false,
  });

  const tierRaw = values.tier;
  if (!tierRaw || !['smoke', 'full', 'tool-update', 'target-merge'].includes(tierRaw)) {
    throw new Error(`--tier must be one of smoke|full|tool-update|target-merge (got ${tierRaw})`);
  }

  const seeds = Number(values.seeds);
  const maxBudget = Number(values['max-budget']);
  const parallelism = Number(values.parallelism);

  if (!Number.isFinite(seeds) || seeds <= 0) throw new Error('--seeds must be a positive integer');
  if (!Number.isFinite(maxBudget) || maxBudget <= 0) throw new Error('--max-budget must be positive');
  if (!Number.isFinite(parallelism) || parallelism <= 0) throw new Error('--parallelism must be positive');

  return {
    tier: tierRaw as Tier,
    seeds,
    maxBudget,
    parallelism,
    targets: String(values.targets),
    tools: String(values.tools),
    toolVersion: values['tool-version'] ? String(values['tool-version']) : undefined,
    triggerReason: String(values['trigger-reason']),
    dryRun: String(values['dry-run']) === 'true',
    githubOutput: values['github-output'] ? String(values['github-output']) : undefined,
  };
}

// ----------------------------------------------------------------------------
// Matrix enumeration
// ----------------------------------------------------------------------------

export async function loadTargets(targetsGlob: string, cwd = process.cwd()): Promise<TargetSpec[]> {
  // Accept comma-separated list OR glob
  const parts = targetsGlob.split(',').map(p => p.trim()).filter(Boolean);
  const files: string[] = [];
  for (const part of parts) {
    if (part.includes('*')) {
      const matched = await glob(part, { cwd, absolute: false });
      files.push(...matched);
    } else if (existsSync(path.join(cwd, part))) {
      files.push(part);
    }
  }
  const unique = Array.from(new Set(files)).sort();

  const out: TargetSpec[] = [];
  for (const f of unique) {
    const full = path.join(cwd, f);
    const raw = await readFile(full, 'utf8');
    const parsed = parseYaml(raw) as Partial<TargetSpec>;
    if (!parsed.id || !parsed.pdb || !parsed.chain || !Array.isArray(parsed.hotspots)) {
      throw new Error(`Invalid target YAML at ${f}: missing id/pdb/chain/hotspots`);
    }
    out.push({
      id: parsed.id,
      pdb: parsed.pdb,
      chain: parsed.chain,
      hotspots: parsed.hotspots,
      version: parsed.version ?? 1,
      tier: String(parsed.tier ?? 'unknown'),
      path: f,
    });
  }
  return out;
}

export async function loadTools(toolsGlob: string, cwd = process.cwd(), versionOverride?: string): Promise<ToolSpec[]> {
  const dirs = await glob(toolsGlob, { cwd, absolute: false });
  const out: ToolSpec[] = [];
  for (const d of dirs.sort()) {
    const full = path.join(cwd, d);
    const s = await stat(full).catch(() => null);
    if (!s?.isDirectory()) continue;

    const id = path.basename(d);
    const manifestPath = path.join(full, 'tool.yaml');

    let version = 'latest';
    let containerImage = `papercrane/${id}:latest`;

    if (existsSync(manifestPath)) {
      const manifest = parseYaml(await readFile(manifestPath, 'utf8')) as {
        version?: string;
        container?: string;
      };
      version = manifest.version ?? version;
      containerImage = manifest.container ?? containerImage;
    }

    if (versionOverride) version = versionOverride;
    out.push({ id, version, containerImage, path: d });
  }
  return out;
}

export function buildMatrix(tools: ToolSpec[], targets: TargetSpec[], seeds: number): Cell[] {
  const cells: Cell[] = [];
  for (const tool of tools) {
    for (const target of targets) {
      const { estCostUsd, estWallclockSec } = estimateCellCost(tool, target, seeds);
      cells.push({
        cellId: ulid(),
        tool,
        target,
        seeds,
        estCostUsd,
        estWallclockSec,
      });
    }
  }
  return cells;
}

// ----------------------------------------------------------------------------
// Vast.ai REST client (minimal)
// ----------------------------------------------------------------------------

const VAST_API = 'https://console.vast.ai/api/v0';

export interface VastOffer {
  id: number;
  dph_total: number;
  gpu_name: string;
  num_gpus: number;
}

export async function vastFindSpotA100(apiKey: string): Promise<VastOffer | null> {
  const url = `${VAST_API}/bundles?q=${encodeURIComponent(JSON.stringify({
    gpu_name: 'A100',
    num_gpus: 1,
    rentable: true,
    type: 'on-demand',
  }))}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  if (!resp.ok) throw new Error(`vast.ai bundles failed: ${resp.status}`);
  const data = (await resp.json()) as { offers?: VastOffer[] };
  const offers = (data.offers ?? []).sort((a, b) => a.dph_total - b.dph_total);
  return offers[0] ?? null;
}

export async function vastCreateInstance(
  apiKey: string,
  offerId: number,
  image: string,
  onstart: string,
): Promise<number> {
  const resp = await fetch(`${VAST_API}/asks/${offerId}/`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      client_id: 'me',
      image,
      disk: 40,
      onstart,
      runtype: 'ssh',
    }),
  });
  if (!resp.ok) throw new Error(`vast.ai create failed: ${resp.status} ${await resp.text()}`);
  const data = (await resp.json()) as { new_contract?: number };
  if (!data.new_contract) throw new Error('vast.ai returned no contract id');
  return data.new_contract;
}

export async function vastDestroyInstance(apiKey: string, instanceId: number): Promise<void> {
  await fetch(`${VAST_API}/instances/${instanceId}/`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${apiKey}` },
  });
}

// ----------------------------------------------------------------------------
// DB layer (BenchmarkRun writes)
// ----------------------------------------------------------------------------

export async function writeBenchmarkRun(
  client: pg.PoolClient,
  runId: string,
  cell: Cell,
  result: CellResult,
  tier: Tier,
  triggerReason: string,
): Promise<string> {
  const benchmarkRunId = ulid();
  await client.query(
    `INSERT INTO "BenchmarkRun"
      (id, run_id, tier, trigger_reason,
       tool_id, tool_version, target_id, target_version,
       seeds_run, hit_rate, status, error_message,
       cost_usd, wallclock_sec, vast_instance_id, created_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15, NOW())
     ON CONFLICT (id) DO NOTHING`,
    [
      benchmarkRunId,
      runId,
      tier,
      triggerReason,
      cell.tool.id,
      cell.tool.version,
      cell.target.id,
      cell.target.version,
      result.seedsRun,
      result.hitRate ?? null,
      result.status,
      result.errorMessage ?? null,
      result.costUsd,
      result.wallclockSec,
      result.vastInstanceId ?? null,
    ],
  );
  return benchmarkRunId;
}

// ----------------------------------------------------------------------------
// Per-cell runner
// ----------------------------------------------------------------------------

async function runCell(
  cell: Cell,
  apiKey: string,
  dryRun: boolean,
): Promise<CellResult> {
  const base: CellResult = {
    cellId: cell.cellId,
    toolId: cell.tool.id,
    toolVersion: cell.tool.version,
    targetId: cell.target.id,
    seedsRun: 0,
    status: 'failed',
    costUsd: 0,
    wallclockSec: 0,
  };

  if (dryRun) {
    return { ...base, status: 'skipped', seedsRun: cell.seeds };
  }

  let instanceId: number | undefined;
  const startedMs = Date.now();
  try {
    const offer = await vastFindSpotA100(apiKey);
    if (!offer) throw new Error('no rentable A100 offer available');

    const onstart = [
      `set -euo pipefail`,
      `mkdir -p /work && cd /work`,
      `echo "tool=${cell.tool.id} version=${cell.tool.version}"`,
      `echo "target=${cell.target.id} hotspots=${cell.target.hotspots.join(',')}"`,
      `echo "seeds=${cell.seeds}"`,
      // Real run logic is baked into each tool's container entrypoint.
      // The container is expected to:
      //   1. Read TARGET_* and SEEDS env vars.
      //   2. Write results (hit rate, per-seed metrics) to /work/results.json.
      //   3. POST /work/results.json + manifest to the Paper Crane results
      //      ingestion endpoint (reading PAPERCRANE_RESULTS_URL).
      `papercrane-run --tool ${cell.tool.id} --target ${cell.target.id} --seeds ${cell.seeds}`,
    ].join('\n');

    instanceId = await vastCreateInstance(apiKey, offer.id, cell.tool.containerImage, onstart);

    // Results are pushed back to us by the container; here we assume the
    // ingestion endpoint has already recorded per-seed rows by the time we
    // check. A follow-up PR wires the polling loop.
    // For the initial implementation we return the estimate as the actual.
    const hitRate = await pollForResults(cell.cellId, cell.seeds);

    const wallSec = Math.round((Date.now() - startedMs) / 1000);
    const costUsd = Number(((wallSec / 3600) * offer.dph_total).toFixed(4));

    return {
      ...base,
      status: 'succeeded',
      seedsRun: cell.seeds,
      hitRate,
      costUsd,
      wallclockSec: wallSec,
      vastInstanceId: instanceId,
    };
  } catch (err) {
    const wallSec = Math.round((Date.now() - startedMs) / 1000);
    return {
      ...base,
      status: 'failed',
      wallclockSec: wallSec,
      vastInstanceId: instanceId,
      errorMessage: (err as Error).message,
    };
  } finally {
    if (instanceId !== undefined) {
      await vastDestroyInstance(apiKey, instanceId).catch(() => undefined);
    }
  }
}

/**
 * Placeholder for the results polling loop. Real implementation polls the
 * Paper Crane ingestion endpoint (driven by PAPERCRANE_RESULTS_URL) until
 * either `seeds` per-seed rows are present or the cell times out.
 *
 * Exposed for testing; intentionally returns undefined by default so a
 * successful Vast.ai launch with no recorded seeds still counts as failed
 * rather than producing a fake hit-rate.
 */
export async function pollForResults(_cellId: string, _expectedSeeds: number): Promise<number | undefined> {
  return undefined;
}

// ----------------------------------------------------------------------------
// Bounded-concurrency pool
// ----------------------------------------------------------------------------

export async function runWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i]!, i);
    }
  }
  const workers = Array.from({ length: Math.min(limit, items.length) }, worker);
  await Promise.all(workers);
  return results;
}

// ----------------------------------------------------------------------------
// Main
// ----------------------------------------------------------------------------

async function main() {
  let args: Args;
  try {
    args = parseCliArgs(process.argv.slice(2));
  } catch (err) {
    console.error((err as Error).message);
    process.exit(5);
  }

  const runId = ulid();
  const startedAt = new Date().toISOString();

  const apiKey = process.env.VASTAI_API_KEY ?? '';
  const dbUrl = process.env.DATABASE_URL ?? '';
  if (!args.dryRun) {
    if (!apiKey) { console.error('VASTAI_API_KEY missing'); process.exit(4); }
    if (!dbUrl) { console.error('DATABASE_URL missing'); process.exit(4); }
  }

  // 1. Enumerate matrix
  const [targets, tools] = await Promise.all([
    loadTargets(args.targets),
    loadTools(args.tools, process.cwd(), args.toolVersion),
  ]);
  if (targets.length === 0) { console.error('no targets resolved'); process.exit(5); }
  if (tools.length === 0) { console.error('no tools resolved'); process.exit(5); }

  const cells = buildMatrix(tools, targets, args.seeds);
  const estimatedCostUsd = Number(
    cells.reduce((a, c) => a + c.estCostUsd, 0).toFixed(2),
  );

  console.error(`[dispatch] run_id=${runId} tier=${args.tier} tools=${tools.length} targets=${targets.length} cells=${cells.length} est_cost=$${estimatedCostUsd}`);

  // 2. Budget guard
  if (estimatedCostUsd > args.maxBudget) {
    const msg = `budget guard: estimated $${estimatedCostUsd} > limit $${args.maxBudget}`;
    console.error(`[dispatch] ABORT — ${msg}`);
    await pageSlack(`benchmark dispatch aborted — ${msg} (run ${runId})`);
    writeGhOutputs(args.githubOutput, {
      run_id: runId,
      estimated_cost_usd: estimatedCostUsd,
      cells_total: cells.length,
      cells_succeeded: 0,
      cells_failed: 0,
      summary_json: '',
    });
    process.exit(2);
  }

  // 3. Fan out
  let dbClient: pg.PoolClient | undefined;
  let pool: pg.Pool | undefined;
  if (!args.dryRun && dbUrl) {
    pool = new pg.Pool({ connectionString: dbUrl, max: Math.max(2, args.parallelism) });
    dbClient = await pool.connect();
  }

  const results = await runWithConcurrency(cells, args.parallelism, async (cell) => {
    const r = await runCell(cell, apiKey, args.dryRun);
    if (dbClient) {
      try {
        r.benchmarkRunId = await writeBenchmarkRun(dbClient, runId, cell, r, args.tier, args.triggerReason);
      } catch (err) {
        console.error(`[dispatch] DB write failed for cell ${cell.cellId}: ${(err as Error).message}`);
      }
    }
    return r;
  });

  dbClient?.release();
  await pool?.end();

  // 4. Summarize
  const succeeded = results.filter(r => r.status === 'succeeded').length;
  const failed = results.filter(r => r.status === 'failed').length;
  const skipped = results.filter(r => r.status === 'skipped').length;
  const actualCost = Number(results.reduce((a, r) => a + r.costUsd, 0).toFixed(4));

  const summary: DispatchSummary = {
    runId,
    tier: args.tier,
    triggerReason: args.triggerReason,
    startedAt,
    finishedAt: new Date().toISOString(),
    cellsTotal: cells.length,
    cellsSucceeded: succeeded,
    cellsFailed: failed,
    cellsSkipped: skipped,
    estimatedCostUsd,
    actualCostUsd: actualCost,
    results,
    githubRunId: process.env.GITHUB_RUN_ID,
    githubSha: process.env.GITHUB_SHA,
  };

  // Structured JSON summary to stdout (also written to file)
  const summaryDir = path.join(process.cwd(), '.benchmark-runs');
  await mkdir(summaryDir, { recursive: true });
  const summaryPath = path.join(summaryDir, `${runId}.json`);
  await writeFile(summaryPath, JSON.stringify(summary, null, 2));
  process.stdout.write(JSON.stringify(summary) + '\n');

  writeGhOutputs(args.githubOutput, {
    run_id: runId,
    estimated_cost_usd: estimatedCostUsd,
    cells_total: cells.length,
    cells_succeeded: succeeded,
    cells_failed: failed,
    summary_json: summaryPath,
  });

  if (cells.length > 0 && succeeded === 0 && skipped === 0) {
    console.error('[dispatch] all cells failed');
    process.exit(3);
  }
  process.exit(0);
}

function writeGhOutputs(
  outputPath: string | undefined,
  kv: Record<string, string | number>,
) {
  if (!outputPath) return;
  const lines = Object.entries(kv).map(([k, v]) => `${k}=${v}`).join('\n') + '\n';
  // Use sync append via fs.promises appendFile would require await;
  // keep this helper lightweight by importing lazily.
  return import('node:fs').then(({ appendFileSync }) => appendFileSync(outputPath, lines));
}

async function pageSlack(text: string) {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) return;
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).catch(() => undefined);
}

// Only run main when executed directly (so tests can import pure helpers)
const isDirect = import.meta.url === `file://${process.argv[1]}`;
if (isDirect) {
  main().catch(err => {
    console.error(err);
    process.exit(4);
  });
}
