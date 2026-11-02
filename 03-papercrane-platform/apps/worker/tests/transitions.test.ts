/**
 * transitions wrapper tests.
 *
 * Ensures the worker-side `transitionJob` both enforces the state machine
 * (via IllegalTransitionError) and updates the DB row + writes an audit
 * entry atomically (single $transaction call).
 */

import { describe, it, expect, vi } from 'vitest';
import { IllegalTransitionError } from '@papercrane/jobs';
import { makeTransitioner } from '../src/transitions';

function mkPrisma(initialStatus: string) {
  const rows = new Map<string, Record<string, unknown> & { id: string; status: string }>();
  rows.set('job-1', { id: 'job-1', status: initialStatus });

  const audit: Array<{ jobId: string; from: string; to: string }> = [];
  let txCalls = 0;

  const prisma = {
    job: {
      findUnique: vi.fn(async ({ where }: { where: { id: string } }) => rows.get(where.id) ?? null),
      update: vi.fn(async ({ where, data }: { where: { id: string }; data: Record<string, unknown> & { status: string } }) => {
        const current = rows.get(where.id)!;
        const next = { ...current, ...data } as Record<string, unknown> & { id: string; status: string };
        rows.set(where.id, next);
        return next;
      }),
    },
    jobAudit: {
      create: vi.fn(async ({ data }: { data: { jobId: string; from: string; to: string } }) => {
        audit.push(data);
        return data;
      }),
    },
    $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) => {
      txCalls += 1;
      return fn(prisma);
    }),
  };

  return { prisma, audit, getTxCalls: () => txCalls, getRow: (id: string) => rows.get(id) };
}

describe('transitionJob', () => {
  it('rejects illegal transitions', async () => {
    const { prisma } = mkPrisma('queued');
    const transitionJob = makeTransitioner(prisma as never, { info: vi.fn(), error: vi.fn() } as never);

    await expect(transitionJob('job-1', 'succeeded')).rejects.toBeInstanceOf(IllegalTransitionError);
  });

  it('updates status and writes audit row in a single transaction', async () => {
    const { prisma, audit, getTxCalls, getRow } = mkPrisma('queued');
    const transitionJob = makeTransitioner(prisma as never, { info: vi.fn(), error: vi.fn() } as never);

    await transitionJob('job-1', 'preparing');

    expect(getRow('job-1')?.status).toBe('preparing');
    expect(audit).toEqual([
      {
        jobId: 'job-1',
        fromStatus: 'queued',
        toStatus: 'preparing',
        actor: 'system',
        reason: null,
      },
    ]);
    expect(getTxCalls()).toBe(1);
  });

  it('no-ops if current status already equals next (idempotent)', async () => {
    const { prisma, audit } = mkPrisma('running');
    const transitionJob = makeTransitioner(prisma as never, { info: vi.fn(), error: vi.fn() } as never);

    await transitionJob('job-1', 'running');
    expect(audit).toHaveLength(0);
  });

  it('persists failure details and a completion timestamp atomically', async () => {
    const { prisma, getRow } = mkPrisma('preparing');
    const transitionJob = makeTransitioner(prisma as never, { info: vi.fn(), error: vi.fn() } as never);
    const error = { code: 'PROVIDER_UNAVAILABLE', message: 'R2 is not configured', retryable: true };

    await transitionJob('job-1', 'failed', { reason: error.message, error });

    expect(getRow('job-1')).toMatchObject({ status: 'failed', error });
    expect(getRow('job-1')?.completedAt).toBeInstanceOf(Date);
  });
});
