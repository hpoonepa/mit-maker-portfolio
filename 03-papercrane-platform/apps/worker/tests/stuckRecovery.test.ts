import { describe, expect, it, vi } from 'vitest';
import type { Queue } from 'bullmq';
import type { Tier } from '@papercrane/jobs';
import type { WorkerContext } from '../src/context';
import { recoverStuckJobs } from '../src/stuckRecovery';

describe('recoverStuckJobs', () => {
  it('fences a stale attempt, records the structured error, and schedules a retry', async () => {
    const stale = {
      id: 'job-1',
      status: 'running' as const,
      attempt: 1,
      queueTier: 'frontier',
      heartbeatAt: new Date('2026-07-21T11:00:00.000Z'),
      startedAt: new Date('2026-07-21T10:59:00.000Z'),
      submittedAt: new Date('2026-07-21T10:58:00.000Z'),
    };
    const add = vi.fn().mockResolvedValue({ id: 'job-1:2' });
    const updateMany = vi.fn().mockResolvedValue({ count: 1 });
    const auditCreate = vi.fn().mockResolvedValue({});
    const transitionJob = vi.fn().mockResolvedValue(undefined);
    const publish = vi.fn().mockResolvedValue(undefined);
    const ctx = {
      prisma: {
        job: { findMany: vi.fn().mockResolvedValue([stale]) },
        jobAudit: { create: auditCreate },
        jobLog: { create: vi.fn().mockResolvedValue({}) },
        $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
          fn({ job: { updateMany }, jobAudit: { create: auditCreate } }),
        ),
      },
      logger: {
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
        debug: vi.fn(),
        child: vi.fn().mockReturnThis(),
      },
      eventPublisher: { publish },
      transitionJob,
    } as unknown as WorkerContext;
    const queue = { add } as unknown as Queue;
    const queues = { free: queue, pro: queue, frontier: queue } satisfies Record<Tier, Queue>;

    const result = await recoverStuckJobs(
      ctx,
      queues,
      20 * 60 * 1000,
      new Date('2026-07-21T12:00:00.000Z'),
    );

    expect(result).toEqual({ inspected: 1, recovered: 1, requeued: 1 });
    expect(updateMany).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          status: 'failed',
          error: expect.objectContaining({ code: 'WORKER_STALLED', retryable: true }),
        }),
      }),
    );
    expect(add).toHaveBeenCalledWith(
      'run-job',
      { jobId: 'job-1', attempt: 2 },
      expect.objectContaining({ jobId: 'job-1:2' }),
    );
    expect(transitionJob).toHaveBeenCalledWith(
      'job-1',
      'queued',
      expect.objectContaining({ actor: 'stuck-job-sweeper' }),
    );
  });

  it('does nothing when a heartbeat was renewed after the scan', async () => {
    const ctx = {
      prisma: {
        job: {
          findMany: vi.fn().mockResolvedValue([
            {
              id: 'job-1',
              status: 'running',
              attempt: 1,
              queueTier: 'pro',
              heartbeatAt: new Date('2026-07-21T11:00:00.000Z'),
              startedAt: null,
              submittedAt: new Date('2026-07-21T10:00:00.000Z'),
            },
          ]),
        },
        $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
          fn({
            job: { updateMany: vi.fn().mockResolvedValue({ count: 0 }) },
            jobAudit: { create: vi.fn() },
          }),
        ),
      },
      logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    } as unknown as WorkerContext;
    const add = vi.fn();
    const queue = { add } as unknown as Queue;

    const result = await recoverStuckJobs(
      ctx,
      { free: queue, pro: queue, frontier: queue },
      20 * 60 * 1000,
      new Date('2026-07-21T12:00:00.000Z'),
    );

    expect(result).toEqual({ inspected: 1, recovered: 0, requeued: 0 });
    expect(add).not.toHaveBeenCalled();
  });
});
