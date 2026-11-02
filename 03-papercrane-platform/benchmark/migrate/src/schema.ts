/**
 * Zod schemas for benchmark migration.
 *
 * These schemas define the normalized shape of data loaded into the Paper
 * Crane leaderboard Postgres database. They intentionally mirror the
 * reproducibility manifest specified in
 * `benchmark/methodology-v1.0.md` §4 and the run manifest in
 * `docs/plans/04-benchmark-engine.md` §2.
 *
 * The migration tool's contract: every historical campaign (God V3B,
 * 5G51 V4, RBX1) is parsed into `BenchmarkRun[]` and loaded idempotently.
 */

import { z } from "zod";

// --- Primitive helpers ----------------------------------------------------

/** SHA-256 hex (64 chars) optionally prefixed with `sha256:`. */
export const sha256Hex = z
  .string()
  .regex(
    /^(sha256:)?[0-9a-f]{64}$/i,
    "expected 64-char hex sha256 (optionally prefixed with 'sha256:')",
  );

/** Amino-acid sequence (1-letter, uppercase, canonical + stop). */
export const aminoAcidSequence = z
  .string()
  .min(1)
  .regex(/^[ACDEFGHIKLMNPQRSTVWYX*]+$/i, "invalid amino-acid sequence");

/** Non-negative integer. */
const nonNegInt = z.number().int().nonnegative();

/** Strictly positive integer. */
const posInt = z.number().int().positive();

// --- Metrics --------------------------------------------------------------

/**
 * Metric bag for a single designed binder. Keys are open-ended — we keep
 * the known validated metrics as typed fields and allow a passthrough for
 * novel metrics (pTMEnergy, LIS, Overath, etc.) that individual campaigns
 * may surface.
 */
export const DesignMetricsSchema = z
  .object({
    // Validated primary metrics (see reference_metric_thresholds.md).
    ipsae: z.number().finite().optional(),
    dockq: z.number().finite().optional(),
    iptm: z.number().finite().optional(),
    ptm: z.number().finite().optional(),
    plddt: z.number().finite().optional(),
    pdockq: z.number().finite().optional(),

    // Novel metrics from the 20-agent sweep (docs/novel_binding_metrics_2025.md).
    ptmenergy: z.number().finite().optional(),
    lis: z.number().finite().optional(),
    overath: z.number().finite().optional(),

    // Interface / structural metrics.
    interface_dg: z.number().finite().optional(),
    interface_sasa: z.number().finite().optional(),
    interface_sc: z.number().finite().optional(),

    // Derived boolean.
    hit: z.boolean().optional(),
  })
  // Allow parser-specific extras without discarding them.
  .catchall(z.union([z.number().finite(), z.string(), z.boolean(), z.null()]));

export type DesignMetrics = z.infer<typeof DesignMetricsSchema>;

// --- DesignResult ---------------------------------------------------------

export const DesignResultSchema = z.object({
  seed: nonNegInt,
  sequence: aminoAcidSequence,
  structurePath: z
    .string()
    .min(1)
    .describe("Relative or absolute path to the predicted PDB/mmCIF file."),
  metrics: DesignMetricsSchema,
  rank: posInt.optional(),
  length: posInt.optional(),
});

export type DesignResult = z.infer<typeof DesignResultSchema>;

// --- BenchmarkRun ---------------------------------------------------------

/** Seed range expressed as `[start, end]` inclusive. */
export const SeedRangeSchema = z
  .tuple([nonNegInt, nonNegInt])
  .refine(([a, b]) => a <= b, {
    message: "seed_range start must be <= end",
  });

export const BenchmarkRunSchema = z.object({
  run_id: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-zA-Z0-9._-]+$/, "run_id must be URL-safe"),
  target_id: z.string().min(1).max(64),
  tool_id: z.string().min(1).max(64),
  tool_version: z.string().min(1).max(64),
  config_hash: sha256Hex,
  seed_range: SeedRangeSchema,
  compute_env_hash: sha256Hex,
  designs: z.array(DesignResultSchema).min(1),
  cost_usd: z.number().finite().nonnegative(),
  wallclock_sec: z.number().finite().nonnegative(),
  results_digest: sha256Hex,
  source: z.enum(["god-v3b", "5g51-v4", "rbx1"]),
  // Optional provenance fields — present in modern runs, absent in legacy.
  created_at: z.string().datetime().optional(),
  git_sha: z.string().max(64).optional(),
  notes: z.string().max(2_000).optional(),
});

export type BenchmarkRun = z.infer<typeof BenchmarkRunSchema>;

// --- BenchmarkCell --------------------------------------------------------

/**
 * Aggregated view of all runs for a single benchmark cell, keyed by the
 * 6-tuple in `docs/plans/04-benchmark-engine.md` §1.
 */
export const BenchmarkCellSchema = z.object({
  target_id: z.string().min(1).max(64),
  tool_id: z.string().min(1).max(64),
  tool_version: z.string().min(1).max(64),
  config_hash: sha256Hex,
  seed_range: SeedRangeSchema,
  compute_env_hash: sha256Hex,
  run_ids: z.array(z.string().min(1)).min(1),
  hit_rate: z.number().finite().min(0).max(1),
  hit_rate_ci_low: z.number().finite().min(0).max(1),
  hit_rate_ci_high: z.number().finite().min(0).max(1),
  mean_ipsae: z.number().finite().optional(),
  mean_dockq: z.number().finite().optional(),
  mean_ptmenergy: z.number().finite().optional(),
  cost_usd_per_hit: z.number().finite().nonnegative().optional(),
});

export type BenchmarkCell = z.infer<typeof BenchmarkCellSchema>;

// --- RunManifest ----------------------------------------------------------

/**
 * Full reproducibility manifest pinned to IPFS + S3, per plan §2.
 * This is a superset of `BenchmarkRun` carrying the raw config and compute
 * environment. `BenchmarkRun` stores only the hashes.
 */
export const ComputeEnvSchema = z.object({
  gpu: z.string().min(1).max(64),
  driver: z.string().min(1).max(64),
  cuda: z.string().min(1).max(32),
  container_digest: sha256Hex,
  provider: z.string().min(1).max(32),
});

export const ToolDescriptorSchema = z.object({
  id: z.string().min(1).max(64),
  version: z.string().min(1).max(64),
  git_sha: z.string().min(1).max(64),
});

export const RunManifestSchema = z.object({
  run_id: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-zA-Z0-9._-]+$/, "run_id must be URL-safe"),
  benchmark_version: z.string().min(1).max(16),
  target_fingerprint: sha256Hex,
  tool: ToolDescriptorSchema,
  config_hash: sha256Hex,
  config: z.record(z.unknown()),
  seed_range: SeedRangeSchema,
  compute: ComputeEnvSchema,
  results_digest: sha256Hex,
  cost_usd: z.number().finite().nonnegative(),
  wallclock_sec: z.number().finite().nonnegative(),
});

export type RunManifest = z.infer<typeof RunManifestSchema>;
export type ComputeEnv = z.infer<typeof ComputeEnvSchema>;
export type ToolDescriptor = z.infer<typeof ToolDescriptorSchema>;

// --- Migration summary ----------------------------------------------------

export const MigrationSummarySchema = z.object({
  runs_parsed: nonNegInt,
  runs_inserted: nonNegInt,
  runs_skipped: nonNegInt,
  designs_inserted: nonNegInt,
  errors: z.array(
    z.object({
      source: z.string(),
      file: z.string().optional(),
      message: z.string(),
    }),
  ),
  dry_run: z.boolean(),
});

export type MigrationSummary = z.infer<typeof MigrationSummarySchema>;
