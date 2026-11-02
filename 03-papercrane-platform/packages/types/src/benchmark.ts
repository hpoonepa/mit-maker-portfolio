import { z } from 'zod';
import { DesignMetricsSchema } from './design';

/**
 * Immutable manifest describing how a benchmark run was configured
 * (plan 04 §2). Stored alongside results for reproducibility.
 */
export const RunManifestSchema = z
  .object({
    runId: z.string().uuid(),
    /** Semver of the benchmark harness. */
    harnessVersion: z.string().min(1),
    /** Git SHA of the harness at run time. */
    gitSha: z
      .string()
      .regex(/^[0-9a-f]{7,40}$/)
      .optional(),
    toolId: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
    toolVersion: z.string().min(1),
    targetSlugs: z.array(z.string().regex(/^[a-z0-9][a-z0-9-]*$/)).min(1),
    seeds: z.array(z.number().int().nonnegative()).min(1),
    numDesignsPerSeed: z.number().int().positive(),
    startedAt: z.string().datetime(),
    notes: z.string().optional(),
  })
  .strict();
export type RunManifest = z.infer<typeof RunManifestSchema>;

/**
 * A single (tool, target, seed) cell of benchmark output.
 */
export const BenchmarkCellSchema = z
  .object({
    runId: z.string().uuid(),
    toolId: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
    targetSlug: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
    seed: z.number().int().nonnegative(),
    numDesigns: z.number().int().nonnegative(),
    /** Passed metric thresholds (composite hit-rate). */
    passCount: z.number().int().nonnegative(),
    /** Aggregate metrics (mean ipsae, etc.). */
    metrics: DesignMetricsSchema,
    wallMinutes: z.number().nonnegative(),
    costUsd: z.number().nonnegative(),
  })
  .strict();
export type BenchmarkCell = z.infer<typeof BenchmarkCellSchema>;

/**
 * Aggregate status of a benchmark run.
 */
export const BenchmarkRunStatusSchema = z.enum([
  'queued',
  'running',
  'succeeded',
  'failed',
  'cancelled',
] as const);
export type BenchmarkRunStatus = z.infer<typeof BenchmarkRunStatusSchema>;

/**
 * Top-level benchmark run record.
 */
export const BenchmarkRunSchema = z
  .object({
    manifest: RunManifestSchema,
    status: BenchmarkRunStatusSchema,
    finishedAt: z.string().datetime().optional(),
    cells: z.array(BenchmarkCellSchema),
  })
  .strict();
export type BenchmarkRun = z.infer<typeof BenchmarkRunSchema>;
