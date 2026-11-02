import { afterEach, describe, expect, it, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext, type AuthContext } from '../src/context.js';
import { betaGateEnabled } from '@papercrane/types';

const AUTH: AuthContext = {
  kind: 'user', userId: '00000000-0000-4000-8000-000000000001',
  orgId: '00000000-0000-4000-8000-000000000002', orgSlug: 'lab', tier: 'pro', scopes: ['*'],
};
const ID = '00000000-0000-4000-8000-000000000003';
const SNAPSHOT = '2026-09-08T12:00:00.000Z';
const row = (i: number) => ({ id: `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`, seed: i });

afterEach(() => vi.unstubAllEnvs());

function callerFor(tx: Record<string, unknown>, auth: AuthContext | null = AUTH) {
  return appRouter.createCaller(createInnerContext({
    auth, prisma: {} as never,
    withRlsUser: vi.fn(async (_p, _uid, fn) => fn(tx)) as never,
  }));
}

describe('export pagination and admission', () => {
  it('returns a continuation after 500 results and preserves scope on the next page', async () => {
    vi.stubEnv('NEXT_PUBLIC_BETA_GATE', 'false');
    const findMany = vi.fn().mockResolvedValueOnce(Array.from({ length: 501 }, (_, i) => row(i)))
      .mockResolvedValueOnce([row(500)]);
    const caller = callerFor({ design: { findMany } });
    const first = await caller.designs.exportPage({ scope: 'project', id: ID, snapshotAt: SNAPSHOT });
    expect(first.items).toHaveLength(500);
    expect(first.items[0]?.provenance).toBe('unknown');
    expect(first.nextCursor).toBe(row(499).id);
    const second = await caller.designs.exportPage({ scope: 'project', id: ID, snapshotAt: SNAPSHOT, cursor: first.nextCursor! });
    expect(second.items).toHaveLength(1);
    expect(second.nextCursor).toBeNull();
    expect(findMany.mock.calls[1]?.[0]).toMatchObject({
      where: { orgId: AUTH.orgId, job: { projectId: ID }, id: { gt: row(499).id }, createdAt: { lte: new Date(SNAPSHOT) } },
      orderBy: { id: 'asc' }, take: 501,
    });
  });

  it('rejects unauthenticated export enumeration', async () => {
    const caller = callerFor({}, null);
    await expect(caller.designs.exportPage({ scope: 'job', id: ID, snapshotAt: SNAPSHOT })).rejects.toThrow(/unauthorized/);
  });

  it('requires designs:read for API-key export enumeration', async () => {
    vi.stubEnv('NEXT_PUBLIC_BETA_GATE', 'false');
    const caller = callerFor({}, { ...AUTH, kind: 'apiKey', apiKeyId: ID, scopes: ['jobs:read'] });
    await expect(caller.designs.exportPage({ scope: 'job', id: ID, snapshotAt: SNAPSHOT })).rejects.toThrow(/designs:read/);
  });

  it.each(['true', 'on', '1'])('blocks direct export API access for an unadmitted user with gate %s', async (flag) => {
    vi.stubEnv('NEXT_PUBLIC_BETA_GATE', flag);
    const findMany = vi.fn();
    const caller = callerFor({ user: { findUnique: async () => ({ betaAccessGrantedAt: null }) }, design: { findMany } });
    await expect(caller.designs.exportPage({ scope: 'job', id: ID, snapshotAt: SNAPSHOT })).rejects.toThrow(/beta invite/);
    expect(findMany).not.toHaveBeenCalled();
    expect(await caller.beta.accessStatus()).toEqual({ granted: false });
  });

  it('allows an admitted user without consuming another invite', async () => {
    vi.stubEnv('NEXT_PUBLIC_BETA_GATE', 'true');
    const caller = callerFor({ user: { findUnique: async () => ({ betaAccessGrantedAt: new Date() }) }, design: { findMany: async () => [] } });
    expect(await caller.designs.exportPage({ scope: 'job', id: ID, snapshotAt: SNAPSHOT })).toEqual({ items: [], nextCursor: null });
  });

  it.each([undefined, '', 'false', 'off', '0'])('keeps explicitly disabled gate %s off', (flag) => {
    expect(betaGateEnabled(flag)).toBe(false);
  });

  it('fails closed for misspelled configuration', () => {
    expect(() => betaGateEnabled('treu')).toThrow(/NEXT_PUBLIC_BETA_GATE/);
  });
});
