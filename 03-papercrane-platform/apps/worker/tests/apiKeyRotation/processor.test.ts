/**
 * API key rotation cleanup — hard-revokes the "old" half of a rotation pair
 * once the 24h grace window lapses.
 *
 * A rotated key has:
 *    rotated_at IS NOT NULL     (it's the old half of a rotation pair)
 *    grace_expires_at IS NOT NULL
 *    revoked_at IS NULL
 *
 * Once `grace_expires_at < now()` the worker flips `revoked_at = now()`. The
 * `auth.verifyApiKey` path already treats `revoked_at IS NOT NULL` as invalid,
 * so callers stop being authenticated immediately on the next request.
 */

import { describe, it, expect, vi } from 'vitest';
import { sweepExpiredGraceKeys } from '../../src/apiKeyRotation/processor';

type ApiKeyRow = {
  id: string;
  rotatedAt: Date | null;
  graceExpiresAt: Date | null;
  revokedAt: Date | null;
};

function mkPrisma(rows: ApiKeyRow[]) {
  const store = new Map(rows.map((r) => [r.id, r]));
  const prisma = {
    apiKey: {
      findMany: vi.fn(
        async ({
          where,
        }: {
          where: {
            rotatedAt: { not: null };
            revokedAt: null;
            graceExpiresAt: { lt: Date };
          };
        }) => {
          return [...store.values()].filter(
            (r) =>
              r.rotatedAt !== null &&
              r.revokedAt === null &&
              r.graceExpiresAt !== null &&
              r.graceExpiresAt < where.graceExpiresAt.lt,
          );
        },
      ),
      updateMany: vi.fn(
        async ({
          where,
          data,
        }: {
          where: { id: { in: string[] }; revokedAt: null };
          data: { revokedAt: Date };
        }) => {
          let count = 0;
          for (const id of where.id.in) {
            const r = store.get(id);
            if (r && r.revokedAt === null) {
              store.set(id, { ...r, revokedAt: data.revokedAt });
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

const mkLogger = () =>
  ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }) as never;

describe('sweepExpiredGraceKeys', () => {
  const NOW = new Date('2026-04-24T12:00:00Z');
  const HOUR = 60 * 60 * 1000;

  it('revokes rotated keys whose grace window has lapsed', async () => {
    const { prisma, store } = mkPrisma([
      // expired grace → should be revoked
      {
        id: 'old-a',
        rotatedAt: new Date(NOW.getTime() - 25 * HOUR),
        graceExpiresAt: new Date(NOW.getTime() - HOUR),
        revokedAt: null,
      },
      // still inside grace → untouched
      {
        id: 'old-b',
        rotatedAt: new Date(NOW.getTime() - HOUR),
        graceExpiresAt: new Date(NOW.getTime() + HOUR),
        revokedAt: null,
      },
      // never rotated (fresh active key) → untouched even though grace null
      {
        id: 'fresh-c',
        rotatedAt: null,
        graceExpiresAt: null,
        revokedAt: null,
      },
      // already revoked → untouched (idempotent, no double-revoke)
      {
        id: 'old-d',
        rotatedAt: new Date(NOW.getTime() - 48 * HOUR),
        graceExpiresAt: new Date(NOW.getTime() - 24 * HOUR),
        revokedAt: new Date(NOW.getTime() - 12 * HOUR),
      },
    ]);

    const n = await sweepExpiredGraceKeys(prisma as never, {
      now: () => NOW,
      logger: mkLogger(),
    });

    expect(n).toBe(1);
    expect(store.get('old-a')?.revokedAt).toEqual(NOW);
    expect(store.get('old-b')?.revokedAt).toBeNull();
    expect(store.get('fresh-c')?.revokedAt).toBeNull();
    // Already-revoked row keeps its original revokedAt unchanged.
    expect(store.get('old-d')?.revokedAt?.toISOString()).toBe(
      new Date(NOW.getTime() - 12 * HOUR).toISOString(),
    );
  });

  it('is a noop when nothing has lapsed', async () => {
    const { prisma } = mkPrisma([
      {
        id: 'old-a',
        rotatedAt: new Date(NOW.getTime() - HOUR),
        graceExpiresAt: new Date(NOW.getTime() + 23 * HOUR),
        revokedAt: null,
      },
    ]);

    const n = await sweepExpiredGraceKeys(prisma as never, {
      now: () => NOW,
      logger: mkLogger(),
    });
    expect(n).toBe(0);
  });

  it('uses the injected clock, not real time', async () => {
    // Row that looks expired by real-time clock but we inject a past "now" so
    // the worker treats it as still-valid. Guards against timezone/DST bugs
    // leaking into tests.
    const realFuture = new Date(Date.now() + 365 * 24 * HOUR);
    const { prisma, store } = mkPrisma([
      {
        id: 'old-e',
        rotatedAt: new Date(Date.now() - HOUR),
        graceExpiresAt: new Date(Date.now() + HOUR),
        revokedAt: null,
      },
    ]);

    const n = await sweepExpiredGraceKeys(prisma as never, {
      now: () => realFuture,
      logger: mkLogger(),
    });
    expect(n).toBe(1);
    expect(store.get('old-e')?.revokedAt).toEqual(realFuture);
  });
});
