/**
 * JobEvent discriminated union + builder helpers.
 *
 * Events are published to Redis pubsub by the worker and fanned out to
 * clients over SSE (`/v1/jobs/:id/events`). See plan 01 §5.
 *
 * The zod schema lives alongside here so `serde.ts` can validate wire
 * messages without reaching into another module.
 */

import { z } from 'zod';
import { JOB_STATUSES, type JobStatus } from './status';

// Metrics kept deliberately loose here: individual tools emit different
// shapes. Downstream services may narrow this — we just preserve the JSON.
export const MetricsSchema = z.record(
  z.union([z.number(), z.string(), z.boolean(), z.null()]),
);
export type Metrics = z.infer<typeof MetricsSchema>;

export const JobStatusSchema = z.enum(JOB_STATUSES);

export const StatusEventSchema = z.object({
  type: z.literal('status'),
  status: JobStatusSchema,
});

export const DesignEventSchema = z.object({
  type: z.literal('design'),
  designId: z.string().min(1),
  seed: z.number().int().nonnegative(),
  metrics: MetricsSchema,
});

export const ProgressEventSchema = z.object({
  type: z.literal('progress'),
  completed: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
});

export const ErrorEventSchema = z.object({
  type: z.literal('error'),
  retryable: z.boolean(),
  message: z.string(),
});

export const JobEventSchema = z.discriminatedUnion('type', [
  StatusEventSchema,
  DesignEventSchema,
  ProgressEventSchema,
  ErrorEventSchema,
]);

export type StatusEvent = z.infer<typeof StatusEventSchema>;
export type DesignEvent = z.infer<typeof DesignEventSchema>;
export type ProgressEvent = z.infer<typeof ProgressEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
export type JobEvent = z.infer<typeof JobEventSchema>;

// ---------- Builders ----------

export function statusEvent(status: JobStatus): StatusEvent {
  return { type: 'status', status };
}

export function designEvent(
  designId: string,
  seed: number,
  metrics: Metrics,
): DesignEvent {
  return { type: 'design', designId, seed, metrics };
}

export function progressEvent(completed: number, total: number): ProgressEvent {
  return { type: 'progress', completed, total };
}

export function errorEvent(retryable: boolean, message: string): ErrorEvent {
  return { type: 'error', retryable, message };
}
