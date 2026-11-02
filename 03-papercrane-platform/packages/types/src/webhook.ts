import { z } from 'zod';
import { JobStatusSchema } from './job';

const WebhookBase = {
  jobId: z.string().uuid(),
  at: z.string().datetime(),
};

export const WebhookJobStatusEventSchema = z
  .object({
    type: z.literal('job.status'),
    ...WebhookBase,
    status: JobStatusSchema,
  })
  .strict();

export const WebhookJobSucceededEventSchema = z
  .object({
    type: z.literal('job.succeeded'),
    ...WebhookBase,
    totalDesigns: z.number().int().nonnegative(),
  })
  .strict();

export const WebhookJobFailedEventSchema = z
  .object({
    type: z.literal('job.failed'),
    ...WebhookBase,
    message: z.string().min(1),
  })
  .strict();

export const WebhookDesignCreatedEventSchema = z
  .object({
    type: z.literal('design.created'),
    ...WebhookBase,
    designId: z.string().uuid(),
  })
  .strict();

/**
 * All webhook payloads the API can fire, discriminated on `type`.
 */
export const WebhookEventSchema = z.discriminatedUnion('type', [
  WebhookJobStatusEventSchema,
  WebhookJobSucceededEventSchema,
  WebhookJobFailedEventSchema,
  WebhookDesignCreatedEventSchema,
]);
export type WebhookEvent = z.infer<typeof WebhookEventSchema>;

/**
 * The subset of event `type` values a subscription can request.
 */
export const WebhookEventTypeSchema = z.enum([
  'job.status',
  'job.succeeded',
  'job.failed',
  'design.created',
] as const);
export type WebhookEventType = z.infer<typeof WebhookEventTypeSchema>;

/**
 * A persistent subscription to one or more webhook event types.
 */
export const WebhookSubscriptionSchema = z
  .object({
    id: z.string().uuid(),
    orgSlug: z.string().regex(/^[a-z0-9][a-z0-9-]*$/),
    url: z.string().url(),
    events: z.array(WebhookEventTypeSchema).min(1),
    secret: z.string().min(8),
    active: z.boolean(),
    createdAt: z.string().datetime(),
    lastDeliveryAt: z.string().datetime().optional(),
  })
  .strict();
export type WebhookSubscription = z.infer<typeof WebhookSubscriptionSchema>;
