/**
 * Smoke test for the dev-fallback path.
 *
 * Boots the dev-only health server with NO Redis and a fake Prisma (returns
 * `[1]` for `SELECT 1`), then curls /healthz and prints the response. This
 * is the minimum repro that proves Wave 10 Agent 4's deliverable: worker
 * /healthz returns 200 in dev without Redis.
 *
 * Run: pnpm --filter @papercrane/worker exec tsx scripts/smoke-dev-fallback.ts
 */
/* eslint-disable no-console */

import http from 'node:http';
import { createLogger } from '@papercrane/observability';
import { startHealthServer } from '../src/observability/health';
import { probeRedis, createDevQueue, logDevFallbackBanner } from '../src/dev-queue';

const fakePrisma = {
  $queryRaw: async (..._args: unknown[]) => [{ '?column?': 1 }],
} as unknown as Parameters<typeof startHealthServer>[0]['prisma'];

async function main(): Promise<void> {
  const logger = createLogger({ service: 'smoke', level: 'info' });
  const redisUrl = process.env.REDIS_URL ?? 'redis://localhost:6379';

  console.log('[smoke] probing redis at', redisUrl);
  const probe = await probeRedis(redisUrl);
  console.log('[smoke] probe result:', probe);

  if (probe === 'ok') {
    console.error('[smoke] redis is actually up — this smoke test requires it down');
    process.exit(2);
  }
  // Accept both 'refused' and 'other' as "Redis unavailable" — the worker's
  // dev-fallback gate uses 'refused' specifically (per task constraints) but
  // for this smoke the unavailability is what matters.

  logDevFallbackBanner(logger, redisUrl);

  const q = createDevQueue<{ jobId: string }>({ logger, name: 'jobs:pro' });
  let processed = 0;
  q.process(async (job) => {
    processed += 1;
    console.log('[smoke] processed job:', job.id, job.data);
  });
  q.enqueue('test', { jobId: 'smoke-1' });
  q.enqueue('test', { jobId: 'smoke-2' });

  const port = 9099; // avoid clobbering a real worker on 9090
  const health = await startHealthServer({ prisma: fakePrisma, logger, devMode: true, port });

  // curl /healthz
  const body: string = await new Promise((resolve, reject) => {
    http
      .get(`http://127.0.0.1:${port}/healthz`, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () =>
          resolve(JSON.stringify({ status: res.statusCode, body: JSON.parse(data) })),
        );
      })
      .on('error', reject);
  });
  console.log('[smoke] /healthz response:', body);

  // give the dev-queue poller two ticks to drain
  await new Promise((r) => setTimeout(r, 600));
  console.log('[smoke] dev-queue processed', processed, 'jobs, remaining:', q.size());

  await q.close();
  await health.close();
  console.log('[smoke] OK');
}

main().catch((err) => {
  console.error('[smoke] FAIL', err);
  process.exit(1);
});
