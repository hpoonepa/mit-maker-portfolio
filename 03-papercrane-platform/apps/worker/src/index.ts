/**
 * `bootstrapWorkers` — starts one BullMQ Worker per tier queue.
 *
 * Plan 03 §7: per-tier queues (`jobs:free`, `jobs:pro`, `jobs:frontier`) with
 * independent concurrency so a Frontier 50K-seed job can't starve a Pro
 * 500-seed job. Each tier gets its own BullMQ Worker instance; all share the
 * same WorkerContext singleton.
 */

import { Worker, Queue, type Job as BullJob } from 'bullmq';
import IORedis from 'ioredis';
import { JOB_QUEUE_NAMES, TIERS, type Tier, type JobError } from '@papercrane/jobs';
import type { WorkerConfig } from './config';
import type { WorkerContext } from './context';
import { processJob } from './jobProcessor';
import { maybeRequeue } from './retryQueue';
import { RETENTION_QUEUE_NAME, purgeExpiredJobs, scheduleRetentionCron } from './retention';
import { attachCancellationListener } from './cancellation';
import { bootstrapWebhookWorker } from './webhooks';
import { bootstrapApiKeyRotationSweeper } from './apiKeyRotation';
import { startHealthServer, type WorkerHealthServer } from './observability/health';
import { initWorkerSentry } from './observability/sentry';
import { recoverStuckJobs } from './stuckRecovery';

export interface BootstrapResult {
  workers: Worker[];
  queues: Record<Tier, Queue>;
  retentionQueue: Queue;
  retentionWorker: Worker;
  cancellationDispose: () => Promise<void>;
  health: WorkerHealthServer;
  close: () => Promise<void>;
}

export async function bootstrapWorkers(
  ctx: WorkerContext,
  config: WorkerConfig,
): Promise<BootstrapResult> {
  const { logger } = ctx;

  // Sentry init (no-op when SENTRY_DSN unset). Fire-and-forget — the dynamic
  // import resolves quickly and any failure is logged inside the helper.
  void initWorkerSentry({
    dsn: process.env.SENTRY_DSN,
    environment: process.env.SENTRY_ENVIRONMENT ?? config.nodeEnv,
    release: process.env.APP_VERSION,
    tracesSampleRate: process.env.SENTRY_TRACES_SAMPLE_RATE
      ? Number.parseFloat(process.env.SENTRY_TRACES_SAMPLE_RATE)
      : undefined,
  });

  // Health probe HTTP server — separate from BullMQ so Fly's TCP/HTTP check
  // doesn't depend on queue state. Fails the probe only when DB or Redis are
  // unreachable (see observability/health.ts).
  const health = await startHealthServer({
    prisma: ctx.prisma,
    redis: ctx.redis,
    logger,
  });

  const connection = { connection: ctx.redis };

  // ---- Per-tier queues (used by retryQueue.ts for requeue) ----
  const queues: Record<Tier, Queue> = {
    free: new Queue(JOB_QUEUE_NAMES.free, connection),
    pro: new Queue(JOB_QUEUE_NAMES.pro, connection),
    frontier: new Queue(JOB_QUEUE_NAMES.frontier, connection),
  };

  // ---- Per-tier workers ----
  const workers: Worker[] = TIERS.map((tier: Tier) => {
    const name = JOB_QUEUE_NAMES[tier];
    const worker = new Worker(
      name,
      async (bullJob: BullJob<{ jobId: string; attempt?: number }>) => {
        const jobId = bullJob.data.jobId;
        const attempt = bullJob.data.attempt ?? 1;
        const result = await processJob(ctx, { jobId, tier, attempt });

        if (result.outcome === 'failed' && result.retryable) {
          const requeued = await maybeRequeue(
            queues,
            {
              jobId,
              tier,
              attempt,
              error: { code: result.errorCode as JobError['code'], message: result.errorMessage ?? '' },
            },
            { logger },
          );
          if (requeued) {
            // Transition the row back to queued so the state machine stays honest.
            await ctx.transitionJob(jobId, 'queued');
          }
        }
        return result;
      },
      { connection: ctx.redis, concurrency: config.concurrency[tier] },
    );

    worker.on('failed', (job: BullJob<{ jobId?: string }> | undefined, err: Error) => {
      logger.error({ tier, jobId: job?.data?.jobId, err }, 'bullmq worker failure');
    });
    worker.on('ready', () => logger.info({ tier, queue: name }, 'worker ready'));

    return worker;
  });

  // ---- Stuck-job recovery ----
  const sweepStuckJobs = () =>
    recoverStuckJobs(ctx, queues, config.jobHeartbeatTimeoutSeconds * 1000).catch((err) => {
      logger.error({ err }, 'stuck-job sweep failed');
    });
  await sweepStuckJobs();
  const stuckJobSweepTimer = setInterval(
    () => void sweepStuckJobs(),
    config.stuckJobSweepIntervalSeconds * 1000,
  );
  stuckJobSweepTimer.unref?.();

  // ---- Retention cron ----
  const retentionQueue = new Queue(RETENTION_QUEUE_NAME, connection);
  const retentionWorker = new Worker(
    RETENTION_QUEUE_NAME,
    async () => {
      await purgeExpiredJobs(ctx.prisma, { logger });
    },
    { connection: ctx.redis, concurrency: 1 },
  );
  await scheduleRetentionCron(retentionQueue, config.retentionIntervalSeconds);

  // ---- Cancellation subscriber (dedicated Redis connection) ----
  const cancelSubscriber = ctx.redis.duplicate();
  const cancellationDispose = await attachCancellationListener(
    cancelSubscriber,
    ctx.cancellation,
    (jobId) => logger.info({ jobId }, 'cancellation requested'),
  );

  // ---- Webhook delivery worker (isolated queue so a slow receiver can't starve job tiers) ----
  const webhook = bootstrapWebhookWorker(ctx, config);

  // ---- API key rotation sweeper (hard-revokes rotated keys once 24h grace lapses) ----
  const apiKeyRotation = bootstrapApiKeyRotationSweeper(ctx);

  const close = async (): Promise<void> => {
    logger.info('bootstrapWorkers.close — draining');
    clearInterval(stuckJobSweepTimer);
    // Stop the health server first so probes start failing immediately and
    // the LB pulls this instance out of rotation before we drain queues.
    try {
      await health.close();
    } catch (err) {
      logger.warn({ err }, 'health server close failed');
    }
    await cancellationDispose();
    try {
      await cancelSubscriber.quit();
    } catch {
      /* already closed */
    }
    await Promise.all(workers.map((w) => w.close()));
    await retentionWorker.close();
    await webhook.close();
    await apiKeyRotation.close();
    await Promise.all(Object.values(queues).map((q) => q.close()));
    await retentionQueue.close();
  };

  return { workers, queues, retentionQueue, retentionWorker, cancellationDispose, health, close };
}

// ---------- Backwards-compatible shim ----------
// The Wave-1 scaffold exported `createWorker`. Keep the name alive so any
// existing imports don't break while we migrate to `bootstrapWorkers`.

export const JOBS_QUEUE_NAME = JOB_QUEUE_NAMES.pro;

export function createWorker(redisUrl = process.env.REDIS_URL ?? 'redis://localhost:6379'): Worker {
  const connection = new IORedis(redisUrl, { maxRetriesPerRequest: null });
  const worker = new Worker(
    JOBS_QUEUE_NAME,
    async () => {
      /* legacy no-op; use bootstrapWorkers in server.ts */
    },
    { connection },
  );
  worker.on('ready', () => {
    // eslint-disable-next-line no-console
    console.log('worker ready (legacy shim)');
  });
  return worker;
}

export default bootstrapWorkers;
export { processJob } from './jobProcessor';
export { makeTransitioner } from './transitions';
export { RedisEventPublisher } from './events';
export { CancellationManager } from './cancellation';
export { buildProviderRegistry, InMemoryProviderRegistry } from './providers';
export type { WorkerContext } from './context';
