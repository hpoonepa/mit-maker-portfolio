/**
 * Webhooks router — CRUD on webhook subscriptions. Deliveries and signing
 * live in a separate worker; the router only manages the registry.
 *
 * The Prisma model is `Webhook` (table `webhooks`) keyed by `orgId`. The DB
 * stores a hashed `secret`; `create` returns the plaintext exactly once via
 * a `{ webhook, secret }` envelope (matches the API-keys reveal-once UX).
 */
import { randomBytes } from 'node:crypto';
import { z } from 'zod';
import { WebhookEventTypeSchema } from '@papercrane/types';
import { hashApiKey } from '@papercrane/auth';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

/** Wire shape for a webhook row — does not include the hashed secret. */
const WebhookRowSchema = z.object({
  id: z.string(),
  orgId: z.string(),
  url: z.string().url(),
  events: z.array(WebhookEventTypeSchema),
  active: z.boolean(),
  lastDeliveredAt: z.date().nullable().optional(),
  lastStatusCode: z.number().int().nullable().optional(),
  failureCount: z.number().int().nonnegative().optional(),
  createdAt: z.date(),
  updatedAt: z.date().optional(),
});

const CreateInput = z
  .object({
    url: z.string().url(),
    events: z.array(WebhookEventTypeSchema).min(1),
  })
  .strict();

const CreateOutput = z.object({
  webhook: WebhookRowSchema,
  /** Plaintext signing secret — surfaced exactly once. */
  secret: z.string(),
});

function generateWebhookSecret(): string {
  return `whsec_${randomBytes(24).toString('base64url')}`;
}

export const webhooksRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/webhooks',
        tags: ['webhooks'],
        summary: 'List webhook subscriptions for the caller’s org',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ items: z.array(WebhookRowSchema) }))
    .query(async ({ ctx }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          webhook: { findMany: (args: unknown) => Promise<unknown[]> };
        };
        return client.webhook.findMany({
          where: { orgId: ctx.auth!.orgId },
          orderBy: { createdAt: 'desc' },
        });
      });
      return { items: items as z.infer<typeof WebhookRowSchema>[] };
    }),

  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/webhooks',
        tags: ['webhooks'],
        summary: 'Create a webhook subscription (returns plaintext secret once)',
        protect: true,
      },
    })
    .input(CreateInput)
    .output(CreateOutput)
    .mutation(async ({ ctx, input }) => {
      const plaintextSecret = generateWebhookSecret();
      const hashedSecret = await hashApiKey(plaintextSecret);
      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              webhook: {
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
              };
            };
            return client.webhook.create({
              data: {
                orgId: ctx.auth!.orgId,
                url: input.url,
                events: input.events,
                secret: hashedSecret,
                active: true,
              },
            });
          },
        );
        return {
          webhook: row as z.infer<typeof WebhookRowSchema>,
          secret: plaintextSecret,
        };
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2002') {
          throw new TRPCError({
            code: 'CONFLICT',
            message: 'a webhook for this URL already exists',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to create webhook',
        });
      }
    }),

  update: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/webhooks/{id}',
        tags: ['webhooks'],
        summary: 'Update a webhook subscription',
        protect: true,
      },
    })
    .input(
      z
        .object({
          id: z.string().min(1),
          url: z.string().url().optional(),
          events: z.array(WebhookEventTypeSchema).min(1).optional(),
          active: z.boolean().optional(),
        })
        .strict(),
    )
    .output(WebhookRowSchema)
    .mutation(async ({ ctx, input }) => {
      const { id, ...data } = input;
      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              webhook: {
                update: (args: {
                  where: Record<string, unknown>;
                  data: Record<string, unknown>;
                }) => Promise<unknown>;
              };
            };
            return client.webhook.update({
              where: { id, orgId: ctx.auth!.orgId },
              data,
            });
          },
        );
        return row as z.infer<typeof WebhookRowSchema>;
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2025') {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'webhook not found' });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to update webhook',
        });
      }
    }),

  delete: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/webhooks/{id}',
        tags: ['webhooks'],
        summary: 'Delete a webhook subscription',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const n = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          webhook: {
            deleteMany: (args: {
              where: Record<string, unknown>;
            }) => Promise<{ count: number }>;
          };
        };
        const r = await client.webhook.deleteMany({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
        return r.count;
      });
      if (n === 0)
        throw new TRPCError({ code: 'NOT_FOUND', message: 'webhook not found' });
      return { ok: true as const };
    }),
});
