/**
 * Retention cron — marks expired jobs as `purged`.
 *
 * Plan 01 §6: "a nightly cron on the orchestrator node runs
 * DELETE FROM jobs WHERE expires_at < now() AND status IN ('succeeded','failed')."
 *
 * We soft-delete (status -> 'purged') rather than hard-delete so audit logs
 * retain the job id. A separate R2 sweeper (future) walks orgs/{id}/jobs/{id}
 * prefixes and drops the actual artifacts.
 *
 * Registered as a BullMQ repeatable job so it runs on a fixed cadence per
 * worker deploy. One worker processes the job; BullMQ uses a Redis lock to
 * prevent stampedes when multiple workers are hot.
 */

import type { Queue } from 'bullmq';
import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';

export const RETENTION_QUEUE_NAME = 'jobs-retention';
export const RETENTION_JOB_NAME = 'purge-expired';

export async function purgeExpiredJobs(
  prisma: PrismaClient,
  opts: { logger: Logger },
): Promise<number> {
  const now = new Date();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const expired = await (prisma as any).job.findMany({
    where: { expiresAt: { lt: now }, status: { in: ['succeeded', 'failed'] } },
  });

  if (expired.length === 0) return 0;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { count } = await (prisma as any).job.updateMany({
    where: { id: { in: expired.map((j: { id: string }) => j.id) } },
    data: { status: 'purged' },
  });

  opts.logger.info({ count }, 'retention: marked expired jobs as purged');
  return count;
}

export async function scheduleRetentionCron(
  queue: Queue,
  intervalSeconds: number,
): Promise<void> {
  await queue.add(
    RETENTION_JOB_NAME,
    {},
    {
      repeat: { every: intervalSeconds * 1000 },
      jobId: RETENTION_JOB_NAME, // dedup — one repeatable per deploy
      removeOnComplete: true,
      removeOnFail: 100,
    },
  );
}
