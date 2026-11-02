/**
 * Unit tests for the notifications router.
 *
 * Covers:
 *   - list: unauthorized, happy path, pagination cursor, validation error
 *   - markAllRead: returns count of rows updated
 *   - preferences.get: defaults merged with stored rows
 *   - preferences.update: validation error on unknown channel
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

const NOTIF_ID = '11111111-1111-4111-8111-111111111111';

const sampleRow = {
  id: NOTIF_ID,
  category: 'job' as const,
  title: 'Job complete',
  description: 'Your job is done',
  actionUrl: '/jobs/123',
  metadata: { jobId: '123' },
  readAt: null,
  createdAt: new Date('2026-04-15T12:00:00Z'),
};

describe('notifications router — list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.notifications.list({})).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns notifications without a cursor when results fit on one page', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        notification: { findMany: vi.fn().mockResolvedValue([sampleRow]) },
      }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.notifications.list({ limit: 25 });
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.id).toBe(NOTIF_ID);
    expect(result.nextCursor).toBeUndefined();
  });

  it('emits nextCursor when more rows exist than the page limit', async () => {
    const rows = [
      sampleRow,
      { ...sampleRow, id: '22222222-2222-4222-8222-222222222222' },
      { ...sampleRow, id: '33333333-3333-4333-8333-333333333333' },
    ];
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({ notification: { findMany: vi.fn().mockResolvedValue(rows) } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.notifications.list({ limit: 2 });
    expect(result.items).toHaveLength(2);
    expect(result.nextCursor).toBeDefined();
  });

  it('rejects bogus limit (Zod validation)', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.notifications.list({ limit: 9999 }),
    ).rejects.toThrow();
  });
});

describe('notifications router — markAllRead', () => {
  it('returns the count of newly-read rows', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        notification: {
          updateMany: vi.fn().mockResolvedValue({ count: 7 }),
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
    const result = await caller.notifications.markAllRead();
    expect(result.count).toBe(7);
  });
});

describe('notifications router — preferences', () => {
  it('merges defaults with stored rows', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({
        notificationPreference: {
          findMany: vi.fn().mockResolvedValue([
            { category: 'job', channel: 'email', enabled: false },
          ]),
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
    const result = await caller.notifications.preferences.get();
    // Stored row override
    expect(result.prefs.job!.email).toBe(false);
    // Default from DEFAULT_PREFERENCES still applies elsewhere
    expect(result.prefs.billing!.in_app).toBe(true);
  });

  it('rejects update with invalid channel (Zod validation)', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.notifications.preferences.update({
        category: 'job',
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        channel: 'sms' as any,
        enabled: true,
      }),
    ).rejects.toThrow();
  });
});
