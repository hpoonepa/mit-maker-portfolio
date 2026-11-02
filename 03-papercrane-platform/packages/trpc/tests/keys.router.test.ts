import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';
import { ROTATION_GRACE_MS } from '../src/routers/keys.js';

/**
 * API keys router — create, rotate (24h grace), revoke.
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

function makeCaller(apiKey: Record<string, unknown>, opts: { now?: () => Date } = {}) {
  const withRlsUser = vi.fn(async (_p, uid, fn) => {
    expect(uid).toBe(USER_ID);
    return fn({ apiKey });
  });
  return appRouter.createCaller(
    createInnerContext({
      auth: AUTH,
      prisma: {} as never,
      withRlsUser: withRlsUser as never,
      now: opts.now,
    }),
  );
}

describe('keys.list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.keys.list()).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('filters out revoked keys via where clause', async () => {
    const findMany = vi.fn().mockResolvedValue([]);
    const caller = makeCaller({ findMany });
    await caller.keys.list();
    const args = findMany.mock.calls[0]![0] as {
      where: { orgId: string; revokedAt: null };
    };
    expect(args.where.orgId).toBe(ORG_ID);
    expect(args.where.revokedAt).toBeNull();
  });
});

describe('keys.create', () => {
  it('persists prefix+hash and returns plaintext secret exactly once', async () => {
    const create = vi.fn().mockResolvedValue({
      id: 'k1',
      name: 'CI',
      prefix: 'pc_live_',
      scopes: ['*'],
      createdAt: new Date('2026-04-25T12:00:00Z'),
    });
    const caller = makeCaller({ create });
    const out = await caller.keys.create({ name: 'CI', scopes: ['*'] });
    expect(typeof out.secret).toBe('string');
    expect(out.secret.length).toBeGreaterThan(20);
    expect(out.key.id).toBe('k1');
    const data = create.mock.calls[0]![0]!.data as {
      orgId: string;
      hash: string;
      prefix: string;
    };
    expect(data.orgId).toBe(ORG_ID);
    expect(data.hash).not.toBe(out.secret); // never store plaintext
    expect(data.prefix.length).toBeGreaterThan(0);
  });
});

describe('keys.rotate', () => {
  const NOW = new Date('2026-04-25T12:00:00Z');

  it('mints a new key and applies a 24h grace to the old row', async () => {
    const oldRow = {
      id: 'k1',
      name: 'CI',
      scopes: ['*'],
      expiresAt: null,
      revokedAt: null,
      rotatedAt: null,
      graceExpiresAt: null,
    };
    const newRow = {
      id: 'k2',
      name: 'CI',
      prefix: 'pc_live_',
      scopes: ['*'],
      createdAt: NOW,
      rotatedFromId: 'k1',
    };
    const findFirst = vi.fn().mockResolvedValue(oldRow);
    const update = vi.fn().mockResolvedValue({});
    const create = vi.fn().mockResolvedValue(newRow);
    const caller = makeCaller(
      { findFirst, update, create },
      { now: () => NOW },
    );
    const out = await caller.keys.rotate({ id: 'k1' });
    expect(out.key.id).toBe('k2');
    expect(out.secret).toMatch(/^pc_live_/);
    // old row stamped with rotatedAt + graceExpiresAt = now + 24h
    const updateArg = update.mock.calls[0]![0]!.data as {
      rotatedAt: Date;
      graceExpiresAt: Date;
    };
    expect(updateArg.rotatedAt).toEqual(NOW);
    expect(updateArg.graceExpiresAt.getTime() - NOW.getTime()).toBe(
      ROTATION_GRACE_MS,
    );
    // new row stamped with rotatedFromId pointing back at the old key
    const createArg = create.mock.calls[0]![0]!.data as {
      rotatedFromId: string;
    };
    expect(createArg.rotatedFromId).toBe('k1');
  });

  it('returns NOT_FOUND when the key does not exist', async () => {
    const findFirst = vi.fn().mockResolvedValue(null);
    const caller = makeCaller({ findFirst });
    await expect(caller.keys.rotate({ id: 'k404' })).rejects.toThrow(
      /not.?found/i,
    );
  });

  it('returns CONFLICT when the key is already rotating', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      id: 'k1',
      name: 'CI',
      scopes: ['*'],
      expiresAt: null,
      revokedAt: null,
      rotatedAt: new Date('2026-04-24T00:00:00Z'),
      graceExpiresAt: new Date('2026-04-25T00:00:00Z'),
    });
    const caller = makeCaller({ findFirst });
    await expect(caller.keys.rotate({ id: 'k1' })).rejects.toThrow(
      /rotat/i,
    );
  });
});

describe('keys.revoke', () => {
  it('flips revoked_at and 404s if no row matches', async () => {
    const updateMany = vi.fn().mockResolvedValue({ count: 0 });
    const caller = makeCaller({ updateMany });
    await expect(caller.keys.revoke({ id: 'k404' })).rejects.toThrow(
      /not.?found|revoked/i,
    );
  });

  it('reports ok:true when one row was revoked', async () => {
    const updateMany = vi.fn().mockResolvedValue({ count: 1 });
    const caller = makeCaller({ updateMany });
    const out = await caller.keys.revoke({ id: 'k1' });
    expect(out.ok).toBe(true);
    const arg = updateMany.mock.calls[0]![0] as {
      where: { id: string; orgId: string; revokedAt: null };
    };
    expect(arg.where.id).toBe('k1');
    expect(arg.where.orgId).toBe(ORG_ID);
    expect(arg.where.revokedAt).toBeNull();
  });
});
