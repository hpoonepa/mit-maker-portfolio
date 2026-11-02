/**
 * Webhook subsystem public surface.
 *
 * The worker's top-level `bootstrapWorkers` composes this alongside the tier
 * queues, but tests and the API can import directly from
 * `./webhooks` for the dispatcher, signer, and types without pulling in
 * BullMQ. Only `bootstrapWebhookWorker` touches BullMQ.
 */

import { Queue, Worker, type Job as BullJob } from 'bullmq';
import type { WorkerConfig } from '../config';
import type { WorkerContext } from '../context';
import { webhookQueueName, webhookJobName } from './queue';
import { processDelivery } from './deliveryProcessor';
import { createDispatcher } from './dispatcher';
import type { DeliveryJob, WebhookQueue } from './types';

export * from './types';
export { signPayload, parseSignatureHeader, verifySignature } from './signer';
export { createDispatcher } from './dispatcher';
export { enqueueWebhookDelivery, webhookQueueName, webhookJobName } from './queue';
export {
  processDelivery,
  computeBackoffMs,
  MAX_ATTEMPTS,
  FAILURE_THRESHOLD,
} from './deliveryProcessor';

export interface WebhookBootstrap {
  queue: Queue;
  worker: Worker;
  dispatcher: ReturnType<typeof createDispatcher>;
  close: () => Promise<void>;
}

/**
 * Start the webhook delivery worker. Returns handles so the caller can wire
 * graceful shutdown alongside the tier workers.
 *
 * Concurrency is isolated from tier workers by virtue of being on its own
 * queue name; a webhook receiver going slow cannot back up Protenix jobs.
 */
export function bootstrapWebhookWorker(
  ctx: WorkerContext,
  config: WorkerConfig,
): WebhookBootstrap {
  const { logger, redis, prisma } = ctx;

  const queue = new Queue(webhookQueueName, { connection: redis });

  // Tests pass a plain `{add}`-shaped object; the real Queue satisfies that
  // contract via structural typing.
  const queueForProcessor = queue as unknown as WebhookQueue;

  const dispatcher = createDispatcher({
    prisma,
    queue: queueForProcessor,
    logger,
  });

  const worker = new Worker<DeliveryJob>(
    webhookQueueName,
    async (bullJob: BullJob<DeliveryJob>) => {
      if (bullJob.name !== webhookJobName) {
        logger.warn({ name: bullJob.name }, 'unknown webhook job name — skipping');
        return;
      }
      await processDelivery(bullJob.data, {
        prisma,
        queue: queueForProcessor,
        logger,
        timeoutMs: config.webhookTimeoutMs,
      });
    },
    {
      connection: redis,
      concurrency: config.webhookConcurrency,
    },
  );

  worker.on('failed', (job: BullJob<DeliveryJob> | undefined, err: Error) => {
    // processDelivery swallows its own errors, so this only fires on
    // unexpected bugs (e.g. prisma connection drops). We deliberately don't
    // re-schedule here — the outer attempt counter is owned by us, not BullMQ.
    logger.error(
      { deliveryId: job?.data?.deliveryId, attempt: job?.data?.attempt, err },
      'webhook worker unexpected failure',
    );
  });

  worker.on('ready', () => logger.info({ queue: webhookQueueName }, 'webhook worker ready'));

  const close = async (): Promise<void> => {
    await worker.close();
    await queue.close();
  };

  return { queue, worker, dispatcher, close };
}
