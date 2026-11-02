/**
 * BullMQ queue wiring for webhook deliveries.
 *
 * Separate from the tier job queues so a thundering-herd of failed webhooks
 * can't starve protein design jobs, and vice versa. Concurrency and retry
 * policy are tuned per-queue in `deliveryProcessor.ts` + `config.ts`.
 */

import type { DeliveryJob, WebhookQueue } from './types';

export const webhookQueueName = 'webhooks-deliver';
export const webhookJobName = 'deliver';

export interface EnqueueOptions {
  /** Delay in milliseconds before BullMQ moves the job from delayed → waiting. */
  delayMs?: number;
}

/**
 * Thin helper so dispatcher + processor share identical enqueue semantics
 * (same job name, same dedup keying). Returns the BullMQ job id.
 */
export async function enqueueWebhookDelivery(
  queue: WebhookQueue,
  delivery: DeliveryJob,
  opts: EnqueueOptions = {},
): Promise<string | null | undefined> {
  const res = await queue.add(webhookJobName, delivery, {
    delay: opts.delayMs,
    // Dedup key = (deliveryId:attempt); prevents a concurrent dispatcher +
    // retry scheduler from double-scheduling the same attempt.
    jobId: `${delivery.deliveryId}:${delivery.attempt}`,
    removeOnComplete: 1000,
    removeOnFail: 1000,
  });
  return res.id;
}
