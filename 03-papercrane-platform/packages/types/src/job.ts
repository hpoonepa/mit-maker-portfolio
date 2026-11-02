import { z } from 'zod';
import { DesignRequestSchema } from './design';
import { WorkflowIdSchema } from './workflow';

/**
 * Job lifecycle — must mirror the state machine in plan 01 §5.
 */
export const JobStatusSchema = z.enum([
  'queued',
  'preparing',
  'running',
  'partial',
  'succeeded',
  'failed',
  'cancelling',
  'cancelled',
  'purged',
] as const);
export type JobStatus = z.infer<typeof JobStatusSchema>;

/**
 * Submission payload accepted by POST /jobs.
 */
export const JobSubmissionSchema = z
  .object({
    toolId: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/),
    /** Trusted Paper Crane workflow. The API resolves its stages server-side. */
    workflowId: WorkflowIdSchema.optional(),
    request: DesignRequestSchema,
    orgSlug: z
      .string()
      .regex(/^[a-z0-9][a-z0-9-]*$/)
      .optional(),
    webhookUrl: z.string().url().optional(),
    idempotencyKey: z.string().min(1).max(255).optional(),
  })
  .strict();
export type JobSubmission = z.infer<typeof JobSubmissionSchema>;

/**
 * Compact job summary for list endpoints / dashboard cards.
 */
export const JobSummarySchema = z
  .object({
    id: z.string().uuid(),
    projectId: z.string().uuid().nullable().optional(),
    // Free-form tool id — accepts pipeline composites like
    // "rfdiffusion+proteinmpnn+boltz2" alongside single-tool slugs.
    toolId: z.string().min(1),
    status: JobStatusSchema,
    submittedAt: z.string().datetime(),
    startedAt: z.string().datetime().optional(),
    finishedAt: z.string().datetime().optional(),
    numDesigns: z.number().int().nonnegative(),
    completedDesigns: z.number().int().nonnegative(),
    errorMessage: z.string().optional(),
  })
  .strict();
export type JobSummary = z.infer<typeof JobSummarySchema>;

/**
 * Streaming job events — discriminated union on `type`.
 */
const JobEventBase = {
  jobId: z.string().uuid(),
  at: z.string().datetime(),
};

export const JobStatusEventSchema = z
  .object({
    type: z.literal('status'),
    ...JobEventBase,
    status: JobStatusSchema,
  })
  .strict();

export const JobDesignEventSchema = z
  .object({
    type: z.literal('design'),
    ...JobEventBase,
    designId: z.string().uuid(),
    seed: z.number().int().nonnegative(),
  })
  .strict();

export const JobProgressEventSchema = z
  .object({
    type: z.literal('progress'),
    ...JobEventBase,
    completed: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const JobErrorEventSchema = z
  .object({
    type: z.literal('error'),
    ...JobEventBase,
    message: z.string().min(1),
    retryable: z.boolean(),
  })
  .strict();

export const JobEventSchema = z.discriminatedUnion('type', [
  JobStatusEventSchema,
  JobDesignEventSchema,
  JobProgressEventSchema,
  JobErrorEventSchema,
]);
export type JobEvent = z.infer<typeof JobEventSchema>;
