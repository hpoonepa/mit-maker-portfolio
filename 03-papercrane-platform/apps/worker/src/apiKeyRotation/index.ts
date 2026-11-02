/**
 * Bootstraps the API-key rotation sweeper.
 *
 * Pattern mirrors `src/retention.ts`: one BullMQ Queue + one Worker, the
 * Worker invokes `sweepExpiredGraceKeys`. A repeatable job is scheduled on
 * queue add; `jobId` dedupes so multiple worker pods don't each schedule
 * their own cron entry.
 *
 * Wire this from `src/index.ts` alongside the existing retention cron.
 */

import { Queue, Worker } from 'bullmq';
import type { WorkerContext } from '../context';
import { sweepExpiredGraceKeys } from './processor';

export const API_KEY_ROTATION_QUEUE_NAME = 'api-keys-rotation-sweep';
export const API_KEY_ROTATION_JOB_NAME = 'sweep-expired-grace-keys';

export interface ApiKeyRotationBootstrap {
  queue: Queue;
  worker: Worker;
  close: () => Promise<void>;
}

export interface ApiKeyRotationOptions {
  /** Cadence in seconds. Default: every 5 minutes — tight enough that a leaked
   * key that triggered a rotation is hard-revoked within 5m of the grace
   * window lapsing, not hours later. */
  intervalSeconds?: number;
}

export function bootstrapApiKeyRotationSweeper(
  ctx: WorkerContext,
  opts: ApiKeyRotationOptions = {},
): ApiKeyRotationBootstrap {
  const interval = opts.intervalSeconds ?? 5 * 60;
  const connection = { connection: ctx.redis };

  const queue = new Queue(API_KEY_ROTATION_QUEUE_NAME, connection);

  const worker = new Worker(
    API_KEY_ROTATION_QUEUE_NAME,
    async () => {
      await sweepExpiredGraceKeys(ctx.prisma, {
        now: () => new Date(),
        logger: ctx.logger,
      });
    },
    { connection: ctx.redis, concurrency: 1 },
  );

  worker.on('failed', (_job, err) => {
    ctx.logger.error({ err }, 'api key rotation sweep failed');
  });
  worker.on('ready', () =>
    ctx.logger.info({ queue: API_KEY_ROTATION_QUEUE_NAME }, 'api key rotation sweeper ready'),
  );

  // Fire-and-forget schedule. Returning a promise here would force every
  // caller to await; we follow the same shape `retention.ts` uses, then
  // surface the scheduling handle on the returned object for tests.
  void queue.add(
    API_KEY_ROTATION_JOB_NAME,
    {},
    {
      repeat: { every: interval * 1000 },
      jobId: API_KEY_ROTATION_JOB_NAME, // dedup repeatable
      removeOnComplete: true,
      removeOnFail: 100,
    },
  );

  const close = async (): Promise<void> => {
    await worker.close();
    await queue.close();
  };

  return { queue, worker, close };
}

export { sweepExpiredGraceKeys } from './processor';
