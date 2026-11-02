import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';
import { DEFAULT_PREFERENCES } from '../src/routers/notifications.js';

/**
 * Notifications router — caller-scoped inbox + preferences.
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

function buildCtx(overrides: {
  notification?: Record<string, unknown>;
  notificationPreference?: Record<string, unknown>;
}) {
  const withRlsUser = vi.fn(async (_p, uid, fn) => {
    expect(uid).toBe(USER_ID);
    return fn({
      notification: overrides.notification,
      notificationPreference: overrides.notificationPreference,
    });
  });
  return createInnerContext({
    auth: AUTH,
    prisma: {} as never,
    withRlsUser: withRlsUser as never,
  });
}

describe('notifications.list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.notifications.list({})).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('paginates with nextCursor when more rows exist than limit', async () => {
    const rows = Array.from({ length: 6 }, (_, i) => ({
      id: `00000000-0000-4000-8000-00000000000${i}`,
      category: 'job' as const,
      title: `t${i}`,
      description: null,
      actionUrl: null,
      metadata: null,
      readAt: null,
      createdAt: new Date(Date.UTC(2026, 3, 20, 0, 0, i)),
    }));
    const findMany = vi.fn().mockResolvedValue(rows);
    const ctx = buildCtx({ notification: { findMany } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.list({ limit: 5 });
    expect(out.items).toHaveLength(5);
    expect(out.nextCursor).toBeDefined();
    // findMany asked for limit+1
    const args = findMany.mock.calls[0]![0] as { take: number };
    expect(args.take).toBe(6);
  });

  it('passes unreadOnly through as readAt:null filter', async () => {
    const findMany = vi.fn().mockResolvedValue([]);
    const ctx = buildCtx({ notification: { findMany } });
    const caller = appRouter.createCaller(ctx);
    await caller.notifications.list({ unreadOnly: true });
    const args = findMany.mock.calls[0]![0] as { where: { readAt: null | unknown } };
    expect(args.where.readAt).toBeNull();
  });
});

describe('notifications.markRead / markAllRead', () => {
  it('markRead is a no-op when no rows match (no leak of existence)', async () => {
    const updateMany = vi.fn().mockResolvedValue({ count: 0 });
    const ctx = buildCtx({ notification: { updateMany } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.markRead({
      id: '00000000-0000-4000-8000-0000000000bb',
    });
    expect(out.ok).toBe(true);
    const args = updateMany.mock.calls[0]![0] as {
      where: { userId: string; readAt: null };
    };
    expect(args.where.userId).toBe(USER_ID);
    expect(args.where.readAt).toBeNull();
  });

  it('markAllRead reports the prisma updateMany count', async () => {
    const updateMany = vi.fn().mockResolvedValue({ count: 7 });
    const ctx = buildCtx({ notification: { updateMany } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.markAllRead();
    expect(out.count).toBe(7);
  });
});

describe('notifications.preferences', () => {
  it('returns the full default map when no rows are stored', async () => {
    const findMany = vi.fn().mockResolvedValue([]);
    const ctx = buildCtx({ notificationPreference: { findMany } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.preferences.get();
    expect(out.prefs).toEqual(DEFAULT_PREFERENCES);
  });

  it('overlays stored rows over the default map', async () => {
    const findMany = vi.fn().mockResolvedValue([
      { category: 'job', channel: 'email', enabled: false },
    ]);
    const ctx = buildCtx({ notificationPreference: { findMany } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.preferences.get();
    expect(out.prefs.job.email).toBe(false);
    // Untouched defaults stay put.
    expect(out.prefs.job.in_app).toBe(true);
    expect(out.prefs.billing).toEqual(DEFAULT_PREFERENCES.billing);
  });

  it('update upserts a single (category, channel) row scoped to userId', async () => {
    const upsert = vi.fn().mockResolvedValue({});
    const ctx = buildCtx({ notificationPreference: { upsert } });
    const caller = appRouter.createCaller(ctx);
    const out = await caller.notifications.preferences.update({
      category: 'job',
      channel: 'email',
      enabled: false,
    });
    expect(out.ok).toBe(true);
    const arg = upsert.mock.calls[0]![0] as {
      where: { userId_category_channel: { userId: string; category: string; channel: string } };
      create: { enabled: boolean };
      update: { enabled: boolean };
    };
    expect(arg.where.userId_category_channel.userId).toBe(USER_ID);
    expect(arg.create.enabled).toBe(false);
    expect(arg.update.enabled).toBe(false);
  });
});
