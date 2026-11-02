/**
 * BullMQ job processor for a single webhook delivery attempt.
 *
 * One job per (deliveryId, attempt). Responsibilities:
 *   1. Load the `webhookDelivery` row + its parent `webhook`. Bail out if the
 *      delivery was deleted or the webhook is already inactive — the sweeper
 *      or a manual disable may have happened between enqueue and pickup.
 *   2. Sign the already-stamped envelope (payload JSON + HMAC over
 *      `${timestamp}.${rawBody}`) and POST it to `webhook.url` with a
 *      `timeoutMs` budget enforced by AbortController.
 *   3. Branch on the response:
 *        • 2xx   → mark delivered, reset failureCount, stamp lastDeliveredAt.
 *        • 5xx / 408 / 429 / network error → bump failureCount, and if
 *          `attempt < MAX_ATTEMPTS` reschedule a new BullMQ job with
 *          delay = min(43_200, 60 * 2^(attempt-1)) seconds (1m, 2m, 4m, 8m,
 *          16m … capped at 12h).
 *        • other 4xx → bump failureCount, do not retry. The receiver is
 *          telling us the request is malformed; retrying won't help.
 *   4. If `failureCount > FAILURE_THRESHOLD` after the bump, flip
 *      `webhook.active = false`. This is the rolling-window circuit breaker:
 *      the retention sweeper resets failureCount when old deliveries age out
 *      of the 7-day window, so this effectively disables hooks that have
 *      been burning for a week.
 *
 * Everything that can throw is caught locally — the processor must always
 * complete cleanly so BullMQ doesn't retry the *job* (we manage retry via
 * explicit enqueue with our own backoff). Throwing out of this function
 * would double-retry because BullMQ's built-in retry would also kick in.
 */

import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';
import { signPayload } from './signer';
import { enqueueWebhookDelivery, webhookJobName } from './queue';
import type { DeliveryJob, WebhookQueue } from './types';

/** Hard cap on attempts including the initial one. attempt 5 is the last try. */
export const MAX_ATTEMPTS = 5;

/** Strictly greater than → disable. Matches spec: "> 20 over rolling 7 days". */
export const FAILURE_THRESHOLD = 20;

/** 12h cap on backoff, in seconds. */
const BACKOFF_CAP_SECONDS = 43_200;

/** HTTP status codes that are worth retrying. */
function isRetryableStatus(status: number): boolean {
  if (status >= 500 && status <= 599) return true;
  if (status === 408 || status === 429) return true;
  return false;
}

/**
 * Exponential backoff for the *next* attempt.
 *   attempt=1 → 60s, attempt=2 → 120s, attempt=3 → 240s, …, capped at 12h.
 * Returns milliseconds (BullMQ's `delay` unit).
 */
export function computeBackoffMs(attempt: number): number {
  const seconds = Math.min(BACKOFF_CAP_SECONDS, 60 * Math.pow(2, attempt - 1));
  return seconds * 1000;
}

export interface ProcessDeliveryDeps {
  prisma: PrismaClient;
  queue: WebhookQueue;
  logger: Logger;
  /** Injected so tests don't hit the network. Defaults to global `fetch`. */
  fetch?: typeof fetch;
  /** Per-request timeout in ms. */
  timeoutMs: number;
}

interface DeliveryRowShape {
  id: string;
  webhookId: string;
  eventType: string;
  payload: unknown;
  attempt: number;
}

interface WebhookRowShape {
  id: string;
  url: string;
  secret: string;
  active: boolean;
  failureCount: number;
}

/**
 * Process a single delivery job. Never throws — all errors are surfaced
 * via logger + retry enqueue + row update.
 */
export async function processDelivery(
  job: DeliveryJob,
  deps: ProcessDeliveryDeps,
): Promise<void> {
  const { prisma, queue, logger, timeoutMs } = deps;
  const fetchImpl = deps.fetch ?? fetch;

  // ---- 1. Load delivery + webhook ----
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const delivery = (await (prisma as any).webhookDelivery.findUnique({
    where: { id: job.deliveryId },
  })) as DeliveryRowShape | null;

  if (!delivery) {
    logger.debug({ deliveryId: job.deliveryId }, 'webhook delivery row missing — skipping');
    return;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const webhook = (await (prisma as any).webhook.findUnique({
    where: { id: delivery.webhookId },
  })) as WebhookRowShape | null;

  if (!webhook) {
    logger.debug({ deliveryId: job.deliveryId, webhookId: delivery.webhookId }, 'webhook row missing — skipping');
    return;
  }

  if (!webhook.active) {
    logger.debug({ webhookId: webhook.id }, 'webhook inactive — skipping delivery');
    return;
  }

  // ---- 2. Sign + POST ----
  const rawBody = JSON.stringify(delivery.payload);
  const signature = signPayload(rawBody, webhook.secret);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let status: number | null = null;
  let responseBody: string | null = null;
  let networkError: Error | null = null;

  try {
    const res = await fetchImpl(webhook.url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'PaperCrane-Webhooks/1.0',
        'X-PaperCrane-Signature': signature,
        'X-PaperCrane-Event': delivery.eventType,
        'X-PaperCrane-Delivery': delivery.id,
      },
      body: rawBody,
      signal: controller.signal,
    });
    status = res.status;
    try {
      // Cap response body we persist so a rogue receiver can't blow up our DB.
      const text = await res.text();
      responseBody = text.length > 4096 ? text.slice(0, 4096) : text;
    } catch {
      responseBody = null;
    }
  } catch (err) {
    networkError = err instanceof Error ? err : new Error(String(err));
  } finally {
    clearTimeout(timer);
  }

  // ---- 3. Branch ----
  const succeeded = status !== null && status >= 200 && status < 300;
  const retryable =
    networkError !== null || (status !== null && isRetryableStatus(status));

  // Persist the attempt outcome on the delivery row. Caller reads
  // statusCode+responseBody to debug failed hooks.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await (prisma as any).webhookDelivery.update({
    where: { id: delivery.id },
    data: {
      statusCode: status,
      responseBody,
      attempt: job.attempt,
    },
  });

  if (succeeded) {
    // Reset failureCount on success — the rolling window is empty by
    // definition if the most recent delivery worked. lastDeliveredAt drives
    // the dashboard "last delivered" display.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (prisma as any).webhook.update({
      where: { id: webhook.id },
      data: {
        lastDeliveredAt: new Date(),
        lastStatusCode: status,
        failureCount: 0,
      },
    });
    logger.info(
      { webhookId: webhook.id, deliveryId: delivery.id, status, attempt: job.attempt },
      'webhook delivered',
    );
    return;
  }

  // Failure path — bump failureCount, possibly disable, possibly requeue.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const updated = (await (prisma as any).webhook.update({
    where: { id: webhook.id },
    data: {
      failureCount: { increment: 1 },
      lastStatusCode: status,
    },
  })) as WebhookRowShape;

  if (updated.failureCount > FAILURE_THRESHOLD) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (prisma as any).webhook.update({
      where: { id: webhook.id },
      data: { active: false },
    });
    logger.warn(
      { webhookId: webhook.id, failureCount: updated.failureCount },
      'webhook disabled — failure threshold exceeded',
    );
  }

  if (retryable && job.attempt < MAX_ATTEMPTS) {
    const delayMs = computeBackoffMs(job.attempt);
    await enqueueWebhookDelivery(
      queue,
      { deliveryId: delivery.id, attempt: job.attempt + 1 },
      { delayMs },
    );
    logger.info(
      {
        webhookId: webhook.id,
        deliveryId: delivery.id,
        status,
        err: networkError?.message,
        attempt: job.attempt,
        nextAttempt: job.attempt + 1,
        delayMs,
      },
      'webhook delivery rescheduled',
    );
    return;
  }

  // Dead-letter: either exhausted attempts or non-retryable status.
  logger.warn(
    {
      webhookId: webhook.id,
      deliveryId: delivery.id,
      status,
      err: networkError?.message,
      attempt: job.attempt,
      terminal: true,
    },
    retryable ? 'webhook delivery exhausted retries' : 'webhook delivery permanent failure',
  );
}

// Re-export the job name so index.ts and bootstrap can wire the BullMQ Worker.
export { webhookJobName };
