/**
 * API keys router — dashboard-facing CRUD + rotation.
 *
 * Create returns the plaintext key exactly once in the response; afterwards
 * we only store the prefix (for UI) and the argon2id hash (for verify).
 *
 * Rotation is a two-row operation:
 *   - mint a new key (full generateApiKey roll)
 *   - mutate the OLD row:
 *       rotated_at       := now()
 *       grace_expires_at := now() + 24h
 *   - stamp the NEW row with `rotated_from_id = old.id` so the audit chain
 *     can be reconstructed.
 *
 * The old row keeps `revoked_at = NULL` so the auth layer accepts it for the
 * next 24h. A worker cron (apps/worker/src/apiKeyRotation/processor.ts)
 * hard-revokes it once the grace window lapses.
 *
 * Revoke is immediate and unconditional — no grace.
 */
import { z } from 'zod';
import { ApiKeyScopeSchema } from '@papercrane/types';
import { generateApiKey } from '@papercrane/auth';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

/** 24h grace window applied to the "old" half of a rotation pair. */
export const ROTATION_GRACE_MS = 24 * 60 * 60 * 1000;

const ApiKeySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  prefix: z.string(),
  scopes: z.array(ApiKeyScopeSchema),
  createdAt: z.date(),
  lastUsedAt: z.date().nullable().optional(),
  expiresAt: z.date().nullable().optional(),
  revokedAt: z.date().nullable().optional(),
  rotatedAt: z.date().nullable().optional(),
  graceExpiresAt: z.date().nullable().optional(),
  rotatedFromId: z.string().nullable().optional(),
});

export type ApiKeySummary = z.infer<typeof ApiKeySummarySchema>;

/**
 * Narrow Prisma client shape — the router treats the transaction client as a
 * bag of CRUD methods so tests can pass bare mocks without pulling in the
 * full generated client.
 */
interface ApiKeyTx {
  apiKey: {
    findMany: (args: unknown) => Promise<unknown[]>;
    findFirst: (args: unknown) => Promise<unknown | null>;
    create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
    update: (args: {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    }) => Promise<unknown>;
    updateMany: (args: {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    }) => Promise<{ count: number }>;
  };
}

export const keysRouter = router({
  /**
   * List active + rotating keys (no revoked rows). Expired keys are included
   * so the UI can surface the "expired" badge until the operator deletes them.
   */
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/keys',
        tags: ['keys'],
        summary: 'List API keys (prefixes only; plaintext is never stored)',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ items: z.array(ApiKeySummarySchema) }))
    .query(async ({ ctx }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as ApiKeyTx;
        return client.apiKey.findMany({
          where: { orgId: ctx.auth!.orgId, revokedAt: null },
          orderBy: { createdAt: 'desc' },
        });
      });
      return { items: items as ApiKeySummary[] };
    }),

  /**
   * Create a new key. `scopes` must be non-empty; `expiresAt` is optional
   * (null = never). Returns `{ key, secret }` where `secret` is the plaintext
   * — surface it in a reveal-once modal and never persist it client-side.
   */
  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/keys',
        tags: ['keys'],
        summary: 'Create an API key — plaintext is returned ONCE',
        protect: true,
      },
    })
    .input(
      z
        .object({
          name: z.string().min(1).max(120),
          scopes: z.array(ApiKeyScopeSchema).min(1),
          expiresAt: z.date().nullable().optional(),
          env: z.enum(['live', 'test']).default('live'),
        })
        .strict(),
    )
    .output(
      z.object({
        key: ApiKeySummarySchema,
        /** Plaintext secret — shown to the user exactly once. */
        secret: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const { fullKey, prefix, hash } = await generateApiKey(input.env);
      const key = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as ApiKeyTx;
        return client.apiKey.create({
          data: {
            orgId: ctx.auth!.orgId,
            name: input.name,
            scopes: input.scopes,
            prefix,
            hash,
            expiresAt: input.expiresAt ?? null,
          },
        });
      });
      return { key: key as ApiKeySummary, secret: fullKey };
    }),

  /**
   * Rotate a key. Preconditions (enforced server-side):
   *   - target row exists, belongs to caller's org
   *   - target is active (revoked_at IS NULL AND rotated_at IS NULL
   *     AND (expires_at IS NULL OR expires_at > now))
   *
   * Postconditions (both writes inside a single RLS-scoped transaction):
   *   - OLD row: rotated_at = now, grace_expires_at = now + 24h
   *   - NEW row inserted with identical {name, scopes, expiresAt} and
   *     rotated_from_id = old.id
   *
   * Returns the NEW key + its plaintext (reveal-once, identical UX to create).
   */
  rotate: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/keys/{id}/rotate',
        tags: ['keys'],
        summary: 'Rotate an API key (old key valid for 24h grace)',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }).strict())
    .output(
      z.object({
        key: ApiKeySummarySchema,
        secret: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const now = ctx.now();
      const graceExpiresAt = new Date(now.getTime() + ROTATION_GRACE_MS);
      const { fullKey, prefix, hash } = await generateApiKey('live');

      const result = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as ApiKeyTx;

        // Load the source row under RLS so cross-org ids error out cleanly.
        const oldRow = (await client.apiKey.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        })) as
          | {
              id: string;
              name: string;
              scopes: string[];
              expiresAt: Date | null;
              revokedAt: Date | null;
              rotatedAt: Date | null;
              graceExpiresAt: Date | null;
            }
          | null;

        if (!oldRow) return { notFound: true as const };
        if (oldRow.revokedAt) return { conflict: 'revoked' as const };
        if (oldRow.rotatedAt) return { conflict: 'already-rotating' as const };
        if (oldRow.expiresAt && oldRow.expiresAt <= now)
          return { conflict: 'expired' as const };

        // Mutate the old row — keep revoked_at NULL so it remains valid during grace.
        await client.apiKey.update({
          where: { id: oldRow.id },
          data: {
            rotatedAt: now,
            graceExpiresAt,
          },
        });

        // Insert the replacement.
        const newRow = (await client.apiKey.create({
          data: {
            orgId: ctx.auth!.orgId,
            name: oldRow.name,
            scopes: oldRow.scopes,
            prefix,
            hash,
            expiresAt: oldRow.expiresAt,
            rotatedFromId: oldRow.id,
          },
        })) as ApiKeySummary;

        return { newRow } as const;
      });

      if ('notFound' in result)
        throw new TRPCError({ code: 'NOT_FOUND', message: 'key not found' });
      if ('conflict' in result)
        throw new TRPCError({
          code: 'CONFLICT',
          message: `cannot rotate: ${result.conflict}`,
        });

      return { key: result.newRow, secret: fullKey };
    }),

  /**
   * Immediate revoke — flips `revoked_at`. Applies to active, rotating, and
   * expired keys alike; the only precondition is that the key is not already
   * revoked. Use this when a secret leaks and the 24h grace is unacceptable.
   */
  revoke: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/keys/{id}/revoke',
        tags: ['keys'],
        summary: 'Revoke an API key immediately',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }).strict())
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const n = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as ApiKeyTx;
        const r = await client.apiKey.updateMany({
          where: { id: input.id, orgId: ctx.auth!.orgId, revokedAt: null },
          data: { revokedAt: ctx.now() },
        });
        return r.count;
      });
      if (n === 0)
        throw new TRPCError({ code: 'NOT_FOUND', message: 'key not found or already revoked' });
      return { ok: true as const };
    }),

  /**
   * Last-used telemetry for a single key. Stub: returns an empty shape with
   * the key id echoed back so the dashboard can render a placeholder card.
   * A future implementation will aggregate from the request log.
   */
  usage: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/keys/{id}/usage',
        tags: ['keys'],
        summary: 'Last-used telemetry for an API key (stub)',
        protect: true,
      },
    })
    .input(
      z
        .object({
          id: z.string().min(1),
          since: z.date().optional(),
        })
        .strict(),
    )
    .output(
      z.object({
        id: z.string(),
        since: z.date().nullable(),
        lastUsedAt: z.date().nullable(),
        /** Request count over the window — 0 until the real impl lands. */
        requests: z.number().int().nonnegative(),
      }),
    )
    .query(async ({ ctx, input }) => {
      // Verify ownership under RLS before returning anything; prevents a
      // cross-org id from leaking existence.
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as ApiKeyTx;
        return client.apiKey.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
      });
      if (!row)
        throw new TRPCError({ code: 'NOT_FOUND', message: 'key not found' });

      return {
        id: input.id,
        since: input.since ?? null,
        lastUsedAt: (row as { lastUsedAt: Date | null }).lastUsedAt ?? null,
        requests: 0,
      };
    }),
});
