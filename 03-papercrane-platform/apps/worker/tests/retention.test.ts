/**
 * Retention cron tests.
 *
 * Plan 01 §6: "a nightly cron on the orchestrator node runs
 * DELETE FROM jobs WHERE expires_at < now() AND status IN ('succeeded','failed')".
 */

import { describe, it, expect, vi } from 'vitest';
import { purgeExpiredJobs } from '../src/retention';

function mkPrisma(rows: Array<{ id: string; status: string; expiresAt: Date }>) {
  const store = new Map(rows.map((r) => [r.id, r]));
  const prisma = {
    job: {
      findMany: vi.fn(async ({ where }: { where: { expiresAt: { lt: Date }; status: { in: string[] } } }) => {
        return [...store.values()].filter(
          (r) => r.expiresAt < where.expiresAt.lt && where.status.in.includes(r.status),
        );
      }),
      updateMany: vi.fn(
        async ({ where, data }: { where: { id: { in: string[] } }; data: { status: string } }) => {
          let count = 0;
          for (const id of where.id.in) {
            const r = store.get(id);
            if (r) {
              store.set(id, { ...r, status: data.status });
              count += 1;
            }
          }
          return { count };
        },
      ),
    },
  };
  return { prisma, store };
}

describe('purgeExpiredJobs', () => {
  it('marks expired succeeded/failed jobs as purged', async () => {
    const past = new Date(Date.now() - 1000 * 60 * 60 * 24 * 30); // 30d ago
    const future = new Date(Date.now() + 1000 * 60 * 60 * 24); // 1d ahead
    const { prisma, store } = mkPrisma([
      { id: 'a', status: 'succeeded', expiresAt: past },
      { id: 'b', status: 'failed', expiresAt: past },
      { id: 'c', status: 'succeeded', expiresAt: future },
      { id: 'd', status: 'running', expiresAt: past }, // non-terminal: untouched
    ]);

    const n = await purgeExpiredJobs(prisma as never, { logger: { info: vi.fn() } as never });
    expect(n).toBe(2);
    expect(store.get('a')?.status).toBe('purged');
    expect(store.get('b')?.status).toBe('purged');
    expect(store.get('c')?.status).toBe('succeeded');
    expect(store.get('d')?.status).toBe('running');
  });

  it('does nothing when no jobs are expired', async () => {
    const future = new Date(Date.now() + 1000 * 60 * 60 * 24);
    const { prisma } = mkPrisma([{ id: 'x', status: 'succeeded', expiresAt: future }]);
    const n = await purgeExpiredJobs(prisma as never, { logger: { info: vi.fn() } as never });
    expect(n).toBe(0);
  });
});
