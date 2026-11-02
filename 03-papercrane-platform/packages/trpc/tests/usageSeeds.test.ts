import { expect, it, vi } from 'vitest';
import { appRouter } from '../src/routers/index';
import { createInnerContext } from '../src/context';

it('reports integer Seeds by tool from current-period consumption', async () => {
  const groupBy = vi.fn().mockResolvedValue([{ tool: 'proteinmpnn', _sum: { seedsConsumed: 3 } }]);
  const caller = appRouter.createCaller(createInnerContext({
    auth: { kind: 'user', userId: 'user-1', orgId: 'org-1', orgSlug: 'lab', tier: 'pro', scopes: ['*'] },
    prisma: {} as never,
    now: () => new Date('2026-10-01T12:00:00Z'),
    withRlsUser: vi.fn(async (_p, _u, fn) => fn({ job: { groupBy } })) as never,
  }));
  expect(await caller.usage.getSeedsByTool()).toEqual({ totals: { proteinmpnn: 3 } });
  expect(groupBy).toHaveBeenCalledWith(expect.objectContaining({ where: {
    orgId: 'org-1', submittedAt: { gte: new Date('2026-10-01T00:00:00Z'), lt: new Date('2026-11-01T00:00:00Z') }, seedsConsumed: { gt: 0 },
  } }));
});
