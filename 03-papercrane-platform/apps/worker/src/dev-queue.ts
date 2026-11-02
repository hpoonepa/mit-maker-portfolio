/**
 * In-memory dev-only queue fallback.
 *
 * When `NODE_ENV !== 'production'` AND the configured Redis returns
 * ECONNREFUSED at startup, the worker boots in "dev fallback" mode:
 *   - no BullMQ
 *   - no ioredis
 *   - a tiny `Map<id, job>` FIFO with `setInterval` polling
 *   - jobs are LOST on restart
 *
 * This file is NEVER imported from the production code path. `server.ts`
 * lazy-imports it ONLY after detecting ECONNREFUSED in dev.
 *
 * Contract: this file does not modify `packages/jobs/`. It re-implements the
 * minimum surface (`enqueue`, `process`) needed for local smoke tests, but
 * does NOT pretend to be BullMQ-compatible.
 */

import type { Logger } from '@papercrane/observability';

/* eslint-disable no-console */

export interface DevJob<T = unknown> {
  id: string;
  name: string;
  data: T;
  enqueuedAt: number;
  attempts: number;
}

export type DevJobHandler<T = unknown> = (job: DevJob<T>) => Promise<void>;

export interface DevQueueOptions {
  /** Polling cadence in ms (default 250). */
  pollMs?: number;
  /** Logger for the warning banner + per-job traces. */
  logger: Logger;
  /** Queue name (cosmetic — only used in logs). */
  name: string;
}

export interface DevQueue<T = unknown> {
  enqueue: (name: string, data: T) => string;
  process: (handler: DevJobHandler<T>) => void;
  size: () => number;
  close: () => Promise<void>;
}

/**
 * Build a tiny FIFO queue. Designed to be created once per "tier" so the
 * server.ts dev branch can mirror the production three-queue topology
 * (`free`, `pro`, `frontier`) without pulling in BullMQ.
 */
export function createDevQueue<T = unknown>(opts: DevQueueOptions): DevQueue<T> {
  const queue: DevJob<T>[] = [];
  let handler: DevJobHandler<T> | null = null;
  let counter = 0;
  let closed = false;

  const tick = async (): Promise<void> => {
    if (closed || !handler || queue.length === 0) return;
    const job = queue.shift()!;
    job.attempts += 1;
    try {
      await handler(job);
    } catch (err) {
      opts.logger.error({ err, jobId: job.id, queue: opts.name }, 'dev-queue handler threw');
    }
  };

  const interval = setInterval(() => {
    void tick();
  }, opts.pollMs ?? 250);
  // Don't keep the event loop alive solely for the dev poller.
  interval.unref?.();

  return {
    enqueue(name: string, data: T): string {
      if (closed) throw new Error('dev-queue closed');
      const id = `${opts.name}-${++counter}`;
      queue.push({ id, name, data, enqueuedAt: Date.now(), attempts: 0 });
      return id;
    },
    process(h: DevJobHandler<T>): void {
      handler = h;
    },
    size(): number {
      return queue.length;
    },
    async close(): Promise<void> {
      closed = true;
      clearInterval(interval);
    },
  };
}

/**
 * Probe whether Redis at `url` is reachable. Resolves to `'ok'` on PONG,
 * `'refused'` on ECONNREFUSED (or DNS failure on a localhost target), or
 * `'other'` on any other error so callers can decide whether to fall back.
 */
export async function probeRedis(
  url: string,
  timeoutMs = 1500,
): Promise<'ok' | 'refused' | 'other'> {
  // Lazy-import ioredis so the dev-fallback path does not require it loaded
  // any earlier than necessary.
  const { default: IORedis } = await import('ioredis');
  const probe = new IORedis(url, {
    lazyConnect: true,
    maxRetriesPerRequest: 1,
    connectTimeout: timeoutMs,
    retryStrategy: () => null, // do not auto-reconnect during probe
  });
  // ioredis emits 'error' even when callers also receive a rejection from
  // `.connect()` — without this listener Node logs a noisy "Unhandled error
  // event" and the rejection sometimes races. We intentionally swallow it.
  let lastErr: NodeJS.ErrnoException | null = null;
  probe.on('error', (e: NodeJS.ErrnoException) => {
    lastErr = e;
  });
  const classify = (err: NodeJS.ErrnoException | null): 'refused' | 'other' => {
    const code = err?.code ?? '';
    const msg = err?.message ?? '';
    if (
      code === 'ECONNREFUSED' ||
      code === 'ENOTFOUND' ||
      code === 'EAI_AGAIN' ||
      /ECONNREFUSED|ENOTFOUND/.test(msg)
    ) {
      return 'refused';
    }
    return 'other';
  };
  try {
    await probe.connect();
    const pong = await probe.ping();
    return pong === 'PONG' ? 'ok' : 'other';
  } catch (err) {
    // Prefer `lastErr` from the 'error' event — ioredis surfaces the real
    // socket error code there ("ECONNREFUSED"), while the rejection from
    // `connect()` is a generic "Connection is closed." with no .code.
    return classify(lastErr ?? (err as NodeJS.ErrnoException));
  } finally {
    try {
      probe.disconnect();
    } catch {
      /* swallow — probe is throwaway */
    }
  }
}

/**
 * Print a single, loud warning the first time we drop to in-memory mode.
 * Intentionally uses both the structured logger AND a stderr banner so it
 * shows up regardless of the app's log level.
 */
export function logDevFallbackBanner(logger: Logger, redisUrl: string): void {
  const msg =
    'Redis not available — using IN-MEMORY queue. Jobs are lost on restart. NOT FOR PROD.';
  logger.warn({ redisUrl }, msg);
  console.warn('\n' + '='.repeat(72));
  console.warn('  WARNING: ' + msg);
  console.warn(`  Configured REDIS_URL: ${redisUrl}`);
  console.warn('  To use real Redis: brew services start redis  (or start Docker Desktop)');
  console.warn('='.repeat(72) + '\n');
}
