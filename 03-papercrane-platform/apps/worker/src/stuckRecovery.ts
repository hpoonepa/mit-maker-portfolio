import type { Queue } from 'bullmq';
import { errorEvent, statusEvent, type Tier } from '@papercrane/jobs';
import type { WorkerContext } from './context';
import { persistJobEvent } from './jobLogs';
import { maybeRequeue } from './retryQueue';

type StaleJob = {
  id: string;
  status: 'preparing' | 'running';
  attempt: number;
  queueTier: string;
  heartbeatAt: Date | null;
  startedAt: Date | null;
  submittedAt: Date;
};

export interface StuckRecoveryResult {
  inspected: number;
  recovered: number;
  requeued: number;
}

/**
 * Fence and retry jobs whose worker heartbeat expired. The conditional update
 * is the ownership check: if a live worker renewed the row after our scan, we
 * leave it alone. Seed persistence also checks `(status, attempt)` so the old
 * worker cannot write after this transition wins.
 */
export async function recoverStuckJobs(
  ctx: WorkerContext,
  queues: Record<Tier, Queue>,
  heartbeatTimeoutMs: number,
  now = new Date(),
): Promise<StuckRecoveryResult> {
  const cutoff = new Date(now.getTime() - heartbeatTimeoutMs);
  const jobModel = ctx.prisma.job as unknown as {
    findMany: (args: unknown) => Promise<StaleJob[]>;
  };
  const staleJobs = await jobModel.findMany({
    where: {
      status: { in: ['preparing', 'running'] },
      OR: [
        { heartbeatAt: { lt: cutoff } },
        { heartbeatAt: null, startedAt: { lt: cutoff } },
        { heartbeatAt: null, startedAt: null, submittedAt: { lt: cutoff } },
      ],
    },
    select: {
      id: true,
      status: true,
      attempt: true,
      queueTier: true,
      heartbeatAt: true,
      startedAt: true,
      submittedAt: true,
    },
    take: 100,
  });

  let recovered = 0;
  let requeued = 0;
  for (const job of staleJobs) {
    const error = {
      code: 'WORKER_STALLED' as const,
      message: `No worker heartbeat since ${(
        job.heartbeatAt ??
        job.startedAt ??
        job.submittedAt
      ).toISOString()}`,
      retryable: true,
      attempt: Math.max(1, job.attempt),
    };

    const won = await ctx.prisma.$transaction(async (tx) => {
      const txAny = tx as unknown as {
        job: { updateMany: (args: unknown) => Promise<{ count: number }> };
        jobAudit: { create: (args: unknown) => Promise<unknown> };
      };
      const updated = await txAny.job.updateMany({
        where: {
          id: job.id,
          status: job.status,
          attempt: job.attempt,
          OR: [
            { heartbeatAt: { lt: cutoff } },
            { heartbeatAt: null, startedAt: { lt: cutoff } },
            { heartbeatAt: null, startedAt: null, submittedAt: { lt: cutoff } },
          ],
        },
        data: { status: 'failed', completedAt: now, error },
      });
      if (updated.count === 0) return false;
      await txAny.jobAudit.create({
        data: {
          jobId: job.id,
          fromStatus: job.status,
          toStatus: 'failed',
          actor: 'stuck-job-sweeper',
          reason: error.message,
        },
      });
      return true;
    });
    if (!won) continue;

    recovered += 1;
    await persistJobEvent(ctx.prisma, ctx.logger, job.id, statusEvent('failed'));
    await persistJobEvent(ctx.prisma, ctx.logger, job.id, errorEvent(true, error.message));
    await ctx.eventPublisher.publish(job.id, statusEvent('failed'));
    await ctx.eventPublisher.publish(job.id, errorEvent(true, error.message));

    const tier: Tier =
      job.queueTier === 'free' || job.queueTier === 'frontier' ? job.queueTier : 'pro';
    const didRequeue = await maybeRequeue(
      queues,
      {
        jobId: job.id,
        tier,
        attempt: Math.max(1, job.attempt),
        error: { code: 'WORKER_STALLED', message: error.message },
      },
      { logger: ctx.logger },
    );
    if (didRequeue) {
      await ctx.transitionJob(job.id, 'queued', {
        actor: 'stuck-job-sweeper',
        reason: 'retrying after expired worker heartbeat',
      });
      await persistJobEvent(ctx.prisma, ctx.logger, job.id, statusEvent('queued'));
      await ctx.eventPublisher.publish(job.id, statusEvent('queued'));
      requeued += 1;
    }
  }

  if (recovered > 0) {
    ctx.logger.warn({ inspected: staleJobs.length, recovered, requeued }, 'stuck jobs recovered');
  }
  return { inspected: staleJobs.length, recovered, requeued };
}
