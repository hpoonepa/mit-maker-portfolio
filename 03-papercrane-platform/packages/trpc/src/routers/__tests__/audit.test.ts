/**
 * Unit tests for the audit router.
 *
 * Covers:
 *   - list: unauthorized, happy path with pagination, validation error
 *   - export: unauthorized, csv format with presigned URL, payload too large
 */
import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../index.js';
import { createTestContext as createInnerContext } from './_helpers.js';
import type { AuthContext } from '../../context.js';

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'free',
  scopes: ['*'],
};

const sampleRow = {
  id: 'audit-1',
  orgId: ORG_ID,
  userId: USER_ID,
  action: 'api_key.created',
  resourceType: 'api_key',
  resourceId: 'key-1',
  metadata: { foo: 'bar' },
  ipAddress: '127.0.0.1',
  userAgent: 'vitest',
  createdAt: new Date('2026-04-01T00:00:00Z'),
  user: { email: 'me@example.com', name: 'Me' },
};

describe('audit router — list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.audit.list({ limit: 10, filters: {} }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('returns mapped items and null cursor when results fit on one page', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        auditLog: {
          findMany: vi.fn().mockResolvedValue([sampleRow]),
        },
      }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.audit.list({ limit: 50, filters: {} });
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.actorEmail).toBe('me@example.com');
    expect(result.nextCursor).toBeNull();
  });

  it('emits a nextCursor when more rows exist than the page limit', async () => {
    const rows = [sampleRow, { ...sampleRow, id: 'audit-2' }, { ...sampleRow, id: 'audit-3' }];
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({ auditLog: { findMany: vi.fn().mockResolvedValue(rows) } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.audit.list({ limit: 2, filters: {} });
    expect(result.items).toHaveLength(2);
    expect(result.nextCursor).toBe('audit-2');
  });

  it('rejects invalid action filter (Zod validation)', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.audit.list({
        limit: 10,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        filters: { actions: ['not_a_real_action' as any] },
      }),
    ).rejects.toThrow();
  });
});

describe('audit router — export', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.audit.export({ format: 'csv', filters: {} }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('returns presigned URL for csv export under row cap', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        auditLog: {
          count: vi.fn().mockResolvedValue(1),
          findMany: vi.fn().mockResolvedValue([sampleRow]),
        },
      }),
    );
    const presignGet = vi.fn(async (key: string) => `https://signed.example/${key}`);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
        presignGet,
        now: () => new Date('2026-04-15T12:00:00Z'),
      }),
    );
    const result = await caller.audit.export({ format: 'csv', filters: {} });
    expect(result.format).toBe('csv');
    expect(result.estimatedRows).toBe(1);
    expect(result.url).toMatch(/^https:\/\/signed\.example\//);
  });

  it('throws PAYLOAD_TOO_LARGE when row count exceeds cap', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        auditLog: {
          count: vi.fn().mockResolvedValue(200_000),
          findMany: vi.fn(),
        },
      }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(
      caller.audit.export({ format: 'jsonl', filters: {} }),
    ).rejects.toThrow(/exceeds/i);
  });
});
