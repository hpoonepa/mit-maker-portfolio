/**
 * keys router — full rotation state machine.
 *
 * State transitions:
 *   created   → rotated → grace-active → revoked (sweeper)
 *                       ↘ revoke (immediate, no grace)
 *
 * The router itself owns the "create new row + mutate old row" half of the
 * rotation. The sweeper (apps/worker/src/apiKeyRotation/processor.ts) owns
 * the eventual hard-revoke once the 24h grace window lapses; this test file
 * fakes that step by calling updateMany with the same predicate so we can
 * assert the full lifecycle inside one suite.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { appRouter } from '../index.js';
import { ROTATION_GRACE_MS } from '../keys.js';
import { createTestContext as createInnerContext } from './_helpers.js';
import type { AuthContext } from '../../context.js';

// crypto-touching pieces of generateApiKey are mocked out — we only care that
// the router stamps {prefix, hash} into the row and returns plaintext once.
vi.mock('@papercrane/auth', () => {
  let n = 0;
  return {
    generateApiKey: vi.fn(async (env: 'live' | 'test') => {
      n += 1;
      const fullKey = `pc_${env}_sk_GEN${n.toString().padStart(23, '0')}`;
      return {
        fullKey,
        prefix: fullKey.slice(0, 8),
        hash: `$argon2id$v=19$mocked-hash-${n}`,
      };
    }),
  };
});

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';
const NOW = new Date('2026-04-24T12:00:00.000Z');

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'pro',
  scopes: ['*'],
};

interface Row {
  id: string;
  orgId: string;
  name: string;
  prefix: string;
  hash: string;
  scopes: string[];
  expiresAt: Date | null;
  revokedAt: Date | null;
  rotatedAt: Date | null;
  graceExpiresAt: Date | null;
  rotatedFromId: string | null;
  createdAt: Date;
  lastUsedAt: Date | null;
}

function mkStore(initial: Row[] = []) {
  const rows = new Map<string, Row>(initial.map((r) => [r.id, r]));
  let id = initial.length;
  const apiKey = {
    findMany: vi.fn(async ({ where }: { where: Record<string, unknown> }) => {
      return [...rows.values()].filter((r) => {
        if (where.orgId && r.orgId !== where.orgId) return false;
        if ('revokedAt' in where && where.revokedAt === null && r.revokedAt !== null)
          return false;
        return true;
      });
    }),
    findFirst: vi.fn(async ({ where }: { where: Record<string, unknown> }) => {
      for (const r of rows.values()) {
        if (where.id && r.id !== where.id) continue;
        if (where.orgId && r.orgId !== where.orgId) continue;
        return r;
      }
      return null;
    }),
    create: vi.fn(async ({ data }: { data: Record<string, unknown> }) => {
      id += 1;
      const newRow: Row = {
        id: `key-${id}`,
        orgId: (data.orgId as string) ?? ORG_ID,
        name: (data.name as string) ?? 'unnamed',
        prefix: (data.prefix as string) ?? 'pc_live_',
        hash: (data.hash as string) ?? 'h',
        scopes: (data.scopes as string[]) ?? [],
        expiresAt: (data.expiresAt as Date | null) ?? null,
        revokedAt: null,
        rotatedAt: null,
        graceExpiresAt: null,
        rotatedFromId: (data.rotatedFromId as string | null) ?? null,
        createdAt: NOW,
        lastUsedAt: null,
      };
      rows.set(newRow.id, newRow);
      return newRow;
    }),
    update: vi.fn(
      async ({
        where,
        data,
      }: {
        where: { id: string };
        data: Record<string, unknown>;
      }) => {
        const cur = rows.get(where.id);
        if (!cur) throw new Error(`row not found: ${where.id}`);
        const next = { ...cur, ...(data as Partial<Row>) };
        rows.set(where.id, next);
        return next;
      },
    ),
    updateMany: vi.fn(
      async ({
        where,
        data,
      }: {
        where: Record<string, unknown>;
        data: Record<string, unknown>;
      }) => {
        let count = 0;
        for (const r of rows.values()) {
          if (where.id && r.id !== where.id) continue;
          if (where.orgId && r.orgId !== where.orgId) continue;
          if ('revokedAt' in where && where.revokedAt === null && r.revokedAt !== null)
            continue;
          rows.set(r.id, { ...r, ...(data as Partial<Row>) });
          count += 1;
        }
        return { count };
      },
    ),
  };
  return { rows, apiKey };
}

function buildCaller(initial: Row[] = []) {
  const { rows, apiKey } = mkStore(initial);
  const withRlsUser = vi.fn(async (_p, userId, fn) => {
    expect(userId).toBe(USER_ID);
    return fn({ apiKey } as never);
  });
  const ctx = createInnerContext({
    auth: AUTH,
    prisma: {} as never,
    withRlsUser: withRlsUser as never,
    now: () => NOW,
  });
  return { caller: appRouter.createCaller(ctx), rows, apiKey };
}

describe('keys.create', () => {
  it('returns plaintext exactly once and persists only prefix + hash', async () => {
    const { caller, rows } = buildCaller();
    const res = await caller.keys.create({
      name: 'production',
      scopes: ['jobs:read'],
      env: 'live',
    });

    // Plaintext returned to caller.
    expect(res.secret).toMatch(/^pc_live_sk_/);
    expect(res.key).toMatchObject({
      prefix: 'pc_live_',
      name: 'production',
    });

    // DB row never holds plaintext.
    const stored = [...rows.values()][0]!;
    expect(stored.hash).toMatch(/^\$argon2id\$/);
    expect(JSON.stringify(stored)).not.toContain(res.secret);
  });

  it('rejects unauthenticated callers', async () => {
    const ctx = createInnerContext({ auth: null });
    const caller = appRouter.createCaller(ctx);
    await expect(
      caller.keys.create({ name: 'x', scopes: ['jobs:read'], env: 'live' }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });
});

describe('keys.rotate — grace window', () => {
  let original: Row;
  beforeEach(() => {
    original = {
      id: 'key-1',
      orgId: ORG_ID,
      name: 'production',
      prefix: 'pc_live_',
      hash: '$argon2id$v=19$old-hash',
      scopes: ['jobs:read'],
      expiresAt: null,
      revokedAt: null,
      rotatedAt: null,
      graceExpiresAt: null,
      rotatedFromId: null,
      createdAt: new Date(NOW.getTime() - 24 * 60 * 60 * 1000),
      lastUsedAt: null,
    };
  });

  it('mints a new key, stamps grace on old, links rotated_from_id', async () => {
    const { caller, rows } = buildCaller([original]);

    const res = await caller.keys.rotate({ id: 'key-1' });

    // New row stamped with 24h grace ancestry.
    expect(res.secret).toMatch(/^pc_live_sk_/);
    expect(res.key.rotatedFromId).toBe('key-1');

    // Old row mutated — grace_expires_at = now + 24h, revoked_at NOT set.
    const old = rows.get('key-1')!;
    expect(old.rotatedAt).toEqual(NOW);
    expect(old.graceExpiresAt).toEqual(new Date(NOW.getTime() + ROTATION_GRACE_MS));
    expect(old.revokedAt).toBeNull(); // critical: still accepted by auth layer

    // ROTATION_GRACE_MS is exactly 24h.
    expect(ROTATION_GRACE_MS).toBe(24 * 60 * 60 * 1000);
  });

  it('both old + new keys are valid during grace (revoked_at NULL on both)', async () => {
    const { caller, rows } = buildCaller([original]);
    await caller.keys.rotate({ id: 'key-1' });

    const oldRow = rows.get('key-1')!;
    const newRow = [...rows.values()].find((r) => r.id !== 'key-1')!;

    // Auth layer treats revoked_at IS NULL as "still valid".
    expect(oldRow.revokedAt).toBeNull();
    expect(newRow.revokedAt).toBeNull();
    // But grace windows differ: new row has none, old expires in 24h.
    expect(newRow.graceExpiresAt).toBeNull();
    expect(oldRow.graceExpiresAt).toEqual(new Date(NOW.getTime() + ROTATION_GRACE_MS));
  });

  it('rejects rotating an already-rotated row (no double-rotation)', async () => {
    const inFlightRotation: Row = {
      ...original,
      rotatedAt: new Date(NOW.getTime() - 60_000),
      graceExpiresAt: new Date(NOW.getTime() + ROTATION_GRACE_MS - 60_000),
    };
    const { caller } = buildCaller([inFlightRotation]);
    await expect(caller.keys.rotate({ id: 'key-1' })).rejects.toThrow(
      /already-rotating/i,
    );
  });

  it('rejects rotating a revoked row', async () => {
    const revoked: Row = { ...original, revokedAt: new Date(NOW.getTime() - 60_000) };
    const { caller } = buildCaller([revoked]);
    await expect(caller.keys.rotate({ id: 'key-1' })).rejects.toThrow(/revoked/i);
  });

  it('cron sweeper hard-revokes once grace lapses', async () => {
    // Pre-condition: row is mid-rotation, grace already expired.
    const expired: Row = {
      ...original,
      rotatedAt: new Date(NOW.getTime() - 25 * 60 * 60 * 1000),
      graceExpiresAt: new Date(NOW.getTime() - 60 * 60 * 1000), // 1h ago
    };
    const { caller, rows, apiKey } = buildCaller([expired]);

    // Sweeper-equivalent updateMany — same predicate the worker uses.
    await apiKey.updateMany({
      where: { id: 'key-1', orgId: ORG_ID, revokedAt: null },
      data: { revokedAt: NOW },
    });

    // After sweep: revoked_at populated.
    expect(rows.get('key-1')!.revokedAt).toEqual(NOW);

    // Subsequent rotate attempt fails with "revoked" not "already-rotating".
    await expect(caller.keys.rotate({ id: 'key-1' })).rejects.toThrow(/revoked/i);
  });
});

describe('keys.revoke — immediate, no grace', () => {
  it('flips revoked_at synchronously with no waiting period', async () => {
    const { caller, rows } = buildCaller([
      {
        id: 'key-1',
        orgId: ORG_ID,
        name: 'leaked',
        prefix: 'pc_live_',
        hash: '$argon2id$v=19$h',
        scopes: ['jobs:read'],
        expiresAt: null,
        revokedAt: null,
        rotatedAt: null,
        graceExpiresAt: null,
        rotatedFromId: null,
        createdAt: NOW,
        lastUsedAt: null,
      },
    ]);

    const res = await caller.keys.revoke({ id: 'key-1' });
    expect(res.ok).toBe(true);

    const after = rows.get('key-1')!;
    expect(after.revokedAt).toEqual(NOW);
    // No grace_expires_at set — revoke skips the rotation state machine.
    expect(after.graceExpiresAt).toBeNull();
  });

  it('rejects revoking an already-revoked key', async () => {
    const { caller } = buildCaller([
      {
        id: 'key-1',
        orgId: ORG_ID,
        name: 'gone',
        prefix: 'pc_live_',
        hash: 'h',
        scopes: ['jobs:read'],
        expiresAt: null,
        revokedAt: new Date(NOW.getTime() - 60_000),
        rotatedAt: null,
        graceExpiresAt: null,
        rotatedFromId: null,
        createdAt: NOW,
        lastUsedAt: null,
      },
    ]);
    await expect(caller.keys.revoke({ id: 'key-1' })).rejects.toThrow(
      /not found or already revoked/i,
    );
  });

  it('revoke during grace short-circuits the sweeper', async () => {
    const inGrace: Row = {
      id: 'key-1',
      orgId: ORG_ID,
      name: 'compromised',
      prefix: 'pc_live_',
      hash: 'h',
      scopes: ['jobs:read'],
      expiresAt: null,
      revokedAt: null,
      rotatedAt: new Date(NOW.getTime() - 60_000),
      graceExpiresAt: new Date(NOW.getTime() + 23 * 60 * 60 * 1000),
      rotatedFromId: null,
      createdAt: NOW,
      lastUsedAt: null,
    };
    const { caller, rows } = buildCaller([inGrace]);
    await caller.keys.revoke({ id: 'key-1' });
    // Immediate — does not wait for grace_expires_at.
    expect(rows.get('key-1')!.revokedAt).toEqual(NOW);
  });
});
