/**
 * Worker process entrypoint.
 *
 *   config → probe redis → prisma → context → bootstrapWorkers → wait for SIGTERM
 *
 * Graceful shutdown sequence (plan 01 §13 — "long-running jobs..."):
 *   1. Stop accepting new jobs (close BullMQ Workers — they finish in-flight).
 *   2. Cancel retention cron.
 *   3. Close Redis + Prisma.
 *   4. Exit.
 *
 * DEV FALLBACK
 * ------------
 * When `NODE_ENV !== 'production'` AND probing Redis returns ECONNREFUSED,
 * the worker boots in "dev fallback" mode: no BullMQ, no ioredis, just an
 * in-memory FIFO queue (see `dev-queue.ts`). /healthz still returns 200 so
 * developers can iterate on API/UI without running Docker. This branch is
 * NEVER taken in production (gated on `nodeEnv` AND probe outcome).
 */

// Load env from monorepo root .env.local before anything else reads process.env.
// Mirrors apps/api/src/server.ts — secrets (DATABASE_URL, REDIS_URL, ...) live
// in the repo-root .env.local that web/worker/app share. Without this,
// `loadWorkerEnv()` below sees an empty DATABASE_URL and crashes at startup.
import { config as loadDotenv } from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// src/server.ts -> ../../../.env.local resolves to <repo>/.env.local
loadDotenv({ path: path.resolve(__dirname, '../../../.env.local') });

import IORedis from 'ioredis';
import { prisma } from '@papercrane/db';
import { createLogger, type Logger } from '@papercrane/observability';
import { loadConfig, type WorkerConfig } from './config';
import { loadWorkerEnv } from './env';
import { bootstrapWorkers } from './index';
import { RedisEventPublisher } from './events';
import { makeTransitioner } from './transitions';
import { CancellationManager } from './cancellation';
import { buildProviderRegistry } from './providers';
import type { WorkerContext } from './context';
import { probeRedis, createDevQueue, logDevFallbackBanner } from './dev-queue';
import { startHealthServer } from './observability/health';
import { runSynthJob } from './processors';
import { createR2Client, type R2Handle } from '@papercrane/storage';

async function startDevFallback(config: WorkerConfig, logger: Logger): Promise<() => Promise<void>> {
  logDevFallbackBanner(logger, config.redisUrl);

  // Three in-memory queues to mirror the production tier topology so any
  // future dev smoke test can enqueue against `free`/`pro`/`frontier` the
  // same way it would in prod.
  const devQueues = {
    free: createDevQueue({ logger, name: 'jobs:free' }),
    pro: createDevQueue({ logger, name: 'jobs:pro' }),
    frontier: createDevQueue({ logger, name: 'jobs:frontier' }),
  };

  // Wire the synthetic processor (dev-only). Each tier runs the same handler
  // because in dev fallback there is no GPU — every job becomes a 5-second
  // simulated tool chain that writes realistic Design rows. Production NEVER
  // reaches this branch (gated on `useDevFallback` in `main`), and the
  // processor itself refuses to run when NODE_ENV=production.
  for (const [tier, q] of Object.entries(devQueues)) {
    q.process(async (job) => {
      const data = (job.data ?? {}) as { jobId?: string; toolId?: string };
      const jobId = data.jobId;
      if (!jobId) {
        logger.warn({ tier, queueJobId: job.id, data }, 'dev-queue: missing jobId payload');
        return;
      }
      logger.info({ tier, jobId, queueJobId: job.id }, 'dev-queue: running synth processor');
      try {
        const result = await runSynthJob(
          { prisma, logger },
          { jobId },
        );
        logger.info({ tier, jobId, result }, 'dev-queue: synth processor finished');
      } catch (err) {
        logger.error({ err, tier, jobId }, 'dev-queue: synth processor threw');
      }
    });
  }

  // Health server in dev mode: redis: false, ok: true (DB still required).
  const health = await startHealthServer({
    prisma,
    logger,
    devMode: true,
    // No `redis` dep passed — health.ts treats this as "redis: false" and,
    // because devMode is set, does not fail the overall probe.
  });

  logger.info(
    { healthPort: health.port, queues: Object.keys(devQueues) },
    'worker ready in DEV FALLBACK mode (in-memory queue, no Redis)',
  );

  return async () => {
    await Promise.all(Object.values(devQueues).map((q) => q.close()));
    await health.close();
  };
}

async function main(): Promise<void> {
  // Crash-fast on bad env BEFORE we touch Prisma, Redis, or BullMQ. Honors
  // `--check-env` (exits 0/1 with a status banner — see @papercrane/env).
  loadWorkerEnv(process.argv);

  const config = loadConfig();
  const logger = createLogger({ service: 'papercrane-worker', level: config.logLevel });
  let storage: R2Handle | undefined;
  try {
    storage = createR2Client();
  } catch (err) {
    logger.warn(
      { err: err instanceof Error ? err.message : String(err) },
      'R2 is not configured; production Modal jobs will fail closed',
    );
  }

  logger.info(
    { env: config.nodeEnv, concurrency: config.concurrency },
    'papercrane worker starting',
  );

  // ---- Redis preflight ----
  // We probe BEFORE constructing the BullMQ workers because BullMQ retries
  // forever on its own connection, which means a missing Redis would never
  // surface as a clean startup error — just an endless backoff loop.
  const probe = await probeRedis(config.redisUrl);
  const useDevFallback = probe === 'refused' && config.nodeEnv !== 'production';

  if (probe !== 'ok' && config.nodeEnv === 'production') {
    logger.error({ redisUrl: config.redisUrl, probe }, 'Redis unreachable in production — aborting');
    process.exit(1);
  }

  let closeFn: () => Promise<void>;
  let redis: IORedis | null = null;

  if (useDevFallback) {
    closeFn = await startDevFallback(config, logger);
  } else {
    redis = new IORedis(config.redisUrl, {
      maxRetriesPerRequest: null,
      enableReadyCheck: true,
    });

    const ctx: WorkerContext = {
      prisma,
      redis,
      logger,
      eventPublisher: new RedisEventPublisher(redis, logger),
      providers: buildProviderRegistry(config, logger, storage),
      cancellation: new CancellationManager(),
      transitionJob: makeTransitioner(prisma, logger),
      storage,
    };

    const boot = await bootstrapWorkers(ctx, config);
    logger.info({ providers: ctx.providers.list() }, 'worker ready to accept jobs');
    closeFn = boot.close;
  }

  let shuttingDown = false;
  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info({ signal }, 'shutdown requested — draining');

    const timeoutMs = config.shutdownTimeoutSeconds * 1000;
    const timer = setTimeout(() => {
      logger.error({ timeoutMs }, 'shutdown timeout exceeded — forcing exit');
      process.exit(1);
    }, timeoutMs);
    timer.unref();

    try {
      await closeFn();
      if (redis) await redis.quit();
      await prisma.$disconnect();
      clearTimeout(timer);
      logger.info('shutdown complete');
      process.exit(0);
    } catch (err) {
      logger.error({ err }, 'shutdown error');
      process.exit(1);
    }
  };

  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('unhandledRejection', (err) => {
    logger.error({ err }, 'unhandledRejection');
  });
  process.on('uncaughtException', (err) => {
    logger.error({ err }, 'uncaughtException');
    void shutdown('SIGTERM');
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error('worker failed to start', err);
  process.exit(1);
});
