import { z } from 'zod';

/**
 * A request to debit seeds from an org's balance (plan 05 §3).
 */
export const SeedConsumeRequestSchema = z
  .object({
    orgSlug: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
    jobId: z.string().uuid(),
    toolId: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
    seeds: z.number().int().nonnegative(),
    idempotencyKey: z.string().min(1).max(255),
  })
  .strict();
export type SeedConsumeRequest = z.infer<typeof SeedConsumeRequestSchema>;

/**
 * Response from POST /usage/consume.
 */
export const SeedConsumeResponseSchema = z
  .object({
    accepted: z.boolean(),
    remainingSeeds: z.number().int().nonnegative(),
    periodEnd: z.string().datetime(),
    ledgerId: z.string().uuid(),
  })
  .strict();
export type SeedConsumeResponse = z.infer<typeof SeedConsumeResponseSchema>;

/**
 * Aggregated usage for a billing period.
 */
export const UsagePeriodSchema = z
  .object({
    orgSlug: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
    periodStart: z.string().datetime(),
    periodEnd: z.string().datetime(),
    seedsIncluded: z.number().int().nonnegative(),
    seedsConsumed: z.number().int().nonnegative(),
    overageSeeds: z.number().int().nonnegative(),
    /** Per-tool breakdown for dashboards / invoices. */
    byTool: z.record(z.string(), z.number().int().nonnegative()),
  })
  .strict();
export type UsagePeriod = z.infer<typeof UsagePeriodSchema>;
