/**
 * API key rotation sweeper.
 *
 * When an operator rotates a key (see packages/trpc/src/routers/keys.ts)
 * the OLD row is mutated:
 *
 *     rotated_at       := now()
 *     grace_expires_at := now() + 24h
 *
 * and left with `revoked_at = NULL` so the auth layer continues to accept
 * incoming requests for 24h. This worker walks those rows and flips
 * `revoked_at` the moment the grace window lapses, executing the equivalent
 * of:
 *
 *     UPDATE api_keys
 *        SET revoked_at = now()
 *      WHERE rotated_at IS NOT NULL
 *        AND revoked_at IS NULL
 *        AND grace_expires_at < now();
 *
 * Deliberately idempotent:
 *   - only rows with `revoked_at IS NULL` are updated
 *   - `count = 0` on empty result is a noop (not an error)
 *
 * A BullMQ repeatable wraps this (see `index.ts`). The sweep runs on a fixed
 * cadence; one worker does the work at a time thanks to BullMQ's Redis lock.
 */

import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';

export interface SweepOptions {
  now: () => Date;
  logger: Logger;
}

export async function sweepExpiredGraceKeys(
  prisma: PrismaClient,
  opts: SweepOptions,
): Promise<number> {
  const now = opts.now();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candidates = await (prisma as any).apiKey.findMany({
    where: {
      rotatedAt: { not: null },
      revokedAt: null,
      graceExpiresAt: { lt: now },
    },
  });

  if (candidates.length === 0) return 0;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { count } = await (prisma as any).apiKey.updateMany({
    where: {
      id: { in: candidates.map((k: { id: string }) => k.id) },
      // Guard against a racing revoke — only flip rows still NULL.
      revokedAt: null,
    },
    data: { revokedAt: now },
  });

  opts.logger.info(
    { count, candidates: candidates.length },
    'apiKeyRotation: revoked expired grace keys',
  );
  return count;
}
