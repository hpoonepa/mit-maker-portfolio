/**
 * Shared utilities for campaign parsers.
 *
 * All three historical campaigns (God V3B, 5G51 V4, RBX1) dump their results
 * as JSON summary files — one per run. The raw shape is nearly identical
 * across campaigns because they all originated from the same Modal/Vast.ai
 * dispatcher; the only differences are `campaign`, the target definition,
 * and per-campaign metric extras. This module defines the common raw shape
 * and the normalization function that maps it to `BenchmarkRun`.
 */

import { readFile, readdir, stat } from "node:fs/promises";
import { join, extname } from "node:path";
import { z } from "zod";
import {
  type BenchmarkRun,
  BenchmarkRunSchema,
  type DesignResult,
} from "../schema.js";
import {
  computeEnvHash,
  configHash,
  resultsDigest,
  stripPrefix,
} from "../hashing.js";

// --- Raw campaign JSON schema --------------------------------------------

const RawTargetSchema = z.object({
  id: z.string().min(1),
  pdb: z.string().min(1),
  chain: z.string().min(1),
  hotspots: z.array(z.number().int()),
  version: z.union([z.number().int(), z.string()]).optional(),
});

const RawToolSchema = z.object({
  id: z.string().min(1),
  version: z.string().min(1),
  git_sha: z.string().min(1).optional(),
});

const RawComputeSchema = z.object({
  gpu: z.string().min(1),
  driver: z.string().min(1),
  cuda: z.string().min(1),
  container_digest: z.string().min(1),
  provider: z.string().min(1),
});

const RawDesignSchema = z.object({
  seed: z.number().int().nonnegative(),
  sequence: z.string().min(1),
  structure: z.string().min(1).optional(),
  structurePath: z.string().min(1).optional(),
  metrics: z.record(z.unknown()),
  rank: z.number().int().positive().optional(),
});

export const RawCampaignRunSchema = z.object({
  campaign: z.string().min(1),
  run_id: z.string().min(1),
  target: RawTargetSchema,
  tool: RawToolSchema,
  config: z.record(z.unknown()),
  compute: RawComputeSchema,
  seed_range: z.tuple([z.number().int(), z.number().int()]),
  cost_usd: z.number().nonnegative(),
  wallclock_sec: z.number().nonnegative(),
  designs: z.array(RawDesignSchema).min(1),
  notes: z.string().optional(),
  created_at: z.string().optional(),
});

export type RawCampaignRun = z.infer<typeof RawCampaignRunSchema>;

// --- Directory walking ----------------------------------------------------

/** Recursively collect absolute paths of JSON files under `root`. */
export async function walkJson(root: string): Promise<string[]> {
  const out: string[] = [];
  async function recurse(dir: string) {
    let entries: string[];
    try {
      entries = await readdir(dir);
    } catch {
      return;
    }
    for (const name of entries) {
      if (name.startsWith(".")) continue;
      const full = join(dir, name);
      const st = await stat(full);
      if (st.isDirectory()) {
        await recurse(full);
      } else if (st.isFile() && extname(name).toLowerCase() === ".json") {
        out.push(full);
      }
    }
  }
  await recurse(root);
  out.sort();
  return out;
}

// --- Normalization --------------------------------------------------------

/**
 * Map raw campaign JSON → `BenchmarkRun`. Performs:
 *   - metric key normalization (lowercase, underscore)
 *   - structure-path field unification (`structure` | `structurePath`)
 *   - config / compute-env hashing
 *   - results-digest computation over the sorted design list
 */
export function normalizeRun(
  raw: RawCampaignRun,
  source: BenchmarkRun["source"],
): BenchmarkRun {
  const designs: DesignResult[] = raw.designs.map((d) => ({
    seed: d.seed,
    sequence: d.sequence.toUpperCase(),
    structurePath: d.structurePath ?? d.structure ?? `designs/seed_${d.seed}.pdb`,
    metrics: normalizeMetrics(d.metrics),
    rank: d.rank,
  }));

  const digest = resultsDigest(
    designs.map((d) => ({
      seed: d.seed,
      sequence: d.sequence,
      metrics: d.metrics,
    })),
  );

  const cfgHash = configHash(raw.config);
  const envHash = computeEnvHash({
    gpu: raw.compute.gpu,
    driver: raw.compute.driver,
    cuda: raw.compute.cuda,
    container_digest: stripPrefix(raw.compute.container_digest),
    provider: raw.compute.provider,
  });

  const run: BenchmarkRun = {
    run_id: raw.run_id,
    target_id: raw.target.id,
    tool_id: raw.tool.id,
    tool_version: raw.tool.version,
    config_hash: cfgHash,
    seed_range: raw.seed_range as [number, number],
    compute_env_hash: envHash,
    designs,
    cost_usd: raw.cost_usd,
    wallclock_sec: raw.wallclock_sec,
    results_digest: digest,
    source,
    created_at: raw.created_at,
    git_sha: raw.tool.git_sha,
    notes: raw.notes,
  };

  // Final validation — guarantees downstream consumers get a clean object.
  return BenchmarkRunSchema.parse(run);
}

function normalizeMetrics(raw: Record<string, unknown>): DesignResult["metrics"] {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined) continue;
    const k = key.toLowerCase().replace(/[\s-]+/g, "_");
    out[k] = value;
  }
  return out as DesignResult["metrics"];
}

// --- Generic parse() implementation --------------------------------------

/**
 * Shared `parse(inputDir)` used by every campaign parser. The per-campaign
 * parser wraps this and asserts the `campaign` field matches its source id,
 * so we never silently merge runs across campaigns.
 */
export async function parseCampaignDir(args: {
  inputDir: string;
  sourceId: BenchmarkRun["source"];
  campaignMatch: (raw: RawCampaignRun) => boolean;
}): Promise<BenchmarkRun[]> {
  const { inputDir, sourceId, campaignMatch } = args;
  const files = await walkJson(inputDir);
  const runs: BenchmarkRun[] = [];
  for (const file of files) {
    const text = await readFile(file, "utf8");
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      throw new Error(
        `failed to parse JSON in ${file}: ${(err as Error).message}`,
      );
    }
    const raw = RawCampaignRunSchema.parse(parsed);
    if (!campaignMatch(raw)) continue;
    runs.push(normalizeRun(raw, sourceId));
  }
  return runs;
}
