import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

/**
 * Audit router — list with filters + cursor pagination, export with size cap.
 */

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'pro',
  scopes: ['*'],
};

function row(over: Record<string, unknown> = {}) {
  return {
    id: 'a1',
    orgId: ORG_ID,
    userId: USER_ID,
    action: 'api_key.created',
    resourceType: 'api_key',
    resourceId: 'k1',
    metadata: { name: 'CI key' },
    ipAddress: '127.0.0.1',
    userAgent: 'curl',
    createdAt: new Date('2026-04-25T12:00:00Z'),
    user: { email: 'h@example.com', name: 'Harsha' },
    ...over,
  };
}

describe('audit.list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.audit.list({ limit: 50, filters: {} }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('scopes the where clause to the caller orgId and forwards filters', async () => {
    const findMany = vi.fn().mockResolvedValue([row()]);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ auditLog: { findMany } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.audit.list({
      limit: 50,
      filters: {
        actions: ['api_key.created'],
        users: [USER_ID],
        from: new Date('2026-04-01T00:00:00Z'),
      },
    });
    expect(out.items).toHaveLength(1);
    expect(out.items[0]!.actorEmail).toBe('h@example.com');
    expect(out.nextCursor).toBeNull();
    const args = findMany.mock.calls[0]![0] as {
      where: {
        orgId: string;
        action: { in: string[] };
        userId: { in: string[] };
        createdAt: { gte: Date };
      };
    };
    expect(args.where.orgId).toBe(ORG_ID);
    expect(args.where.action.in).toEqual(['api_key.created']);
    expect(args.where.userId.in).toEqual([USER_ID]);
    expect(args.where.createdAt.gte).toBeInstanceOf(Date);
  });

  it('returns a nextCursor when more rows exist than limit', async () => {
    const rows = Array.from({ length: 4 }, (_, i) =>
      row({ id: `a${i}`, createdAt: new Date(Date.UTC(2026, 3, 20, 0, 0, i)) }),
    );
    const findMany = vi.fn().mockResolvedValue(rows);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ auditLog: { findMany } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.audit.list({ limit: 3, filters: {} });
    expect(out.items).toHaveLength(3);
    expect(out.nextCursor).toBe('a2');
  });
});

describe('audit.export', () => {
  it('refuses when row count exceeds the hard cap', async () => {
    const count = vi.fn().mockResolvedValue(100_001);
    const findMany = vi.fn().mockResolvedValue([]);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ auditLog: { count, findMany } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(
      caller.audit.export({ format: 'csv', filters: {} }),
    ).rejects.toThrow(/exceeds|narrow/i);
  });

  it('returns presigned URL + estimatedRows when within cap', async () => {
    const count = vi.fn().mockResolvedValue(2);
    const items = [row({ id: 'r1' }), row({ id: 'r2', action: 'webhook.created' })];
    const findMany = vi.fn().mockResolvedValue(items);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ auditLog: { count, findMany } }),
    );
    const presignGet = vi.fn(async (key: string) => `https://signed/${key}`);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
        presignGet,
        now: () => new Date('2026-04-25T12:00:00Z'),
      }),
    );
    const out = await caller.audit.export({ format: 'csv', filters: {} });
    expect(out.estimatedRows).toBe(2);
    expect(out.format).toBe('csv');
    expect(out.url).toMatch(/^https:\/\/signed\//);
    expect(presignGet).toHaveBeenCalled();
  });
});
