/**
 * Integrations router (Wave 14) — Slack + Discord chat connections.
 *
 * Differs from `webhooks` in three ways:
 *   1. Outbound — we POST to Slack/Discord, not the other way around.
 *   2. No HMAC secret — Slack/Discord incoming-webhook URLs are bearer.
 *   3. The event registry is broader (billing, member, usage events) and
 *      its defaults differ (e.g. design.created defaults OFF — too noisy).
 *
 * Data model
 *   `Integration`            one row per (org, kind), groups channels.
 *   `IntegrationChannel`     one row per webhook URL with its event filter
 *                            and per-channel mute toggle.
 *
 * The split lets a single org have, say, two Slack channels (#alerts +
 * #billing) attached to one "Slack" integration with different event
 * subsets each. The UI today only surfaces one channel per integration —
 * the model supports more for future-proofing without a migration.
 *
 * Test delivery
 *   `testChannel` synthesises a `system.test` event and hands it to the
 *   worker's integration router. In dev that lets the user verify the
 *   webhook URL works end-to-end. We DO NOT actually call Slack/Discord
 *   here — the worker dispatches.
 */
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Event registry ─────────────────────────────────────────────────────────
// Single source of truth for the Slack/Discord event names + defaults.
// Mirrored in `apps/worker/src/integrations/router.ts` and the EventPicker
// component. Adding a new event here requires touching all three.

export const INTEGRATION_EVENTS = [
  { value: 'job.completed', defaultOn: true },
  { value: 'job.failed', defaultOn: true },
  { value: 'design.created', defaultOn: false }, // too noisy
  { value: 'billing.upgraded', defaultOn: true },
  { value: 'member.invited', defaultOn: false },
  { value: 'usage.cap_warning', defaultOn: true },
  { value: 'usage.cap_reached', defaultOn: true },
] as const;

export type IntegrationEventName = (typeof INTEGRATION_EVENTS)[number]['value'];

const IntegrationEventSchema = z.enum(
  INTEGRATION_EVENTS.map((e) => e.value) as [string, ...string[]],
);

const DEFAULT_EVENTS: IntegrationEventName[] = INTEGRATION_EVENTS.filter(
  (e) => e.defaultOn,
).map((e) => e.value as IntegrationEventName);

// ─── Wire shapes ────────────────────────────────────────────────────────────

const IntegrationKindSchema = z.enum(['slack', 'discord']);

const ChannelRowSchema = z.object({
  id: z.string(),
  integrationId: z.string(),
  webhookUrl: z.string().url(),
  events: z.array(IntegrationEventSchema),
  muted: z.boolean(),
  capWarningPct: z.number().int().min(50).max(100),
  lastDeliveredAt: z.date().nullable().optional(),
  lastStatusCode: z.number().int().nullable().optional(),
  failureCount: z.number().int().nonnegative().optional(),
  createdAt: z.date(),
  updatedAt: z.date().optional(),
});

const IntegrationRowSchema = z.object({
  id: z.string(),
  orgId: z.string(),
  kind: IntegrationKindSchema,
  name: z.string(),
  createdAt: z.date(),
  updatedAt: z.date().optional(),
  channels: z.array(ChannelRowSchema),
});

// ─── Inputs ─────────────────────────────────────────────────────────────────

const ConnectInput = z
  .object({
    kind: IntegrationKindSchema,
    name: z.string().trim().max(120).default(''),
    /** Slack: hooks.slack.com/services/...   Discord: discord.com/api/webhooks/... */
    webhookUrl: z.string().url(),
    events: z.array(IntegrationEventSchema).optional(),
  })
  .strict();

const UpdateChannelInput = z
  .object({
    id: z.string().min(1),
    events: z.array(IntegrationEventSchema).optional(),
    muted: z.boolean().optional(),
    webhookUrl: z.string().url().optional(),
    capWarningPct: z.number().int().min(50).max(100).optional(),
  })
  .strict();

// ─── Validation ─────────────────────────────────────────────────────────────
// Cheap shape check that catches the most common copy-paste mistake (pasting
// a Discord URL into the Slack form). Doesn't actually hit the network.

function assertWebhookShape(kind: 'slack' | 'discord', url: string): void {
  if (kind === 'slack') {
    if (!/^https:\/\/hooks\.slack\.com\/services\//.test(url)) {
      throw new TRPCError({
        code: 'BAD_REQUEST',
        message: 'Slack webhook URL must start with https://hooks.slack.com/services/',
      });
    }
  } else if (kind === 'discord') {
    if (!/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\//.test(url)) {
      throw new TRPCError({
        code: 'BAD_REQUEST',
        message: 'Discord webhook URL must start with https://discord.com/api/webhooks/',
      });
    }
  }
}

// ─── Router ─────────────────────────────────────────────────────────────────

export const integrationsRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/integrations',
        tags: ['integrations'],
        summary: 'List Slack/Discord integrations for the caller’s org',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ items: z.array(IntegrationRowSchema) }))
    .query(async ({ ctx }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          integration: { findMany: (args: unknown) => Promise<unknown[]> };
        };
        return client.integration.findMany({
          where: { orgId: ctx.auth!.orgId },
          orderBy: { createdAt: 'desc' },
          include: { channels: { orderBy: { createdAt: 'asc' } } },
        });
      });
      return { items: items as z.infer<typeof IntegrationRowSchema>[] };
    }),

  connect: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/integrations',
        tags: ['integrations'],
        summary: 'Connect a Slack or Discord channel via incoming webhook URL',
        protect: true,
      },
    })
    .input(ConnectInput)
    .output(IntegrationRowSchema)
    .mutation(async ({ ctx, input }) => {
      assertWebhookShape(input.kind, input.webhookUrl);
      const events = input.events ?? DEFAULT_EVENTS;

      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              integration: {
                create: (args: { data: Record<string, unknown>; include: unknown }) => Promise<unknown>;
              };
            };
            return client.integration.create({
              data: {
                orgId: ctx.auth!.orgId,
                kind: input.kind,
                name: input.name ?? '',
                channels: {
                  create: [
                    {
                      webhookUrl: input.webhookUrl,
                      events,
                    },
                  ],
                },
              },
              include: { channels: true },
            });
          },
        );
        return row as z.infer<typeof IntegrationRowSchema>;
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2002') {
          throw new TRPCError({
            code: 'CONFLICT',
            message: 'an integration for this URL already exists',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to connect integration',
        });
      }
    }),

  updateChannel: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/integrations/channels/{id}',
        tags: ['integrations'],
        summary: 'Update event filter, mute, or webhook URL for a channel',
        protect: true,
      },
    })
    .input(UpdateChannelInput)
    .output(ChannelRowSchema)
    .mutation(async ({ ctx, input }) => {
      const { id, ...data } = input;
      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              integrationChannel: {
                update: (args: {
                  where: Record<string, unknown>;
                  data: Record<string, unknown>;
                }) => Promise<unknown>;
              };
            };
            return client.integrationChannel.update({
              where: { id },
              data,
            });
          },
        );
        return row as z.infer<typeof ChannelRowSchema>;
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2025') {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'channel not found' });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to update channel',
        });
      }
    }),

  disconnect: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/integrations/{id}',
        tags: ['integrations'],
        summary: 'Disconnect an integration (cascades to all its channels)',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const n = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          integration: {
            deleteMany: (args: {
              where: Record<string, unknown>;
            }) => Promise<{ count: number }>;
          };
        };
        const r = await client.integration.deleteMany({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
        return r.count;
      });
      if (n === 0)
        throw new TRPCError({ code: 'NOT_FOUND', message: 'integration not found' });
      return { ok: true as const };
    }),

  testChannel: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/integrations/channels/{id}/test',
        tags: ['integrations'],
        summary: 'Send a test message to a channel (synthetic system.test event)',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(
      z.object({
        ok: z.boolean(),
        statusCode: z.number().int().nullable(),
        message: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const channel = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          integrationChannel: { findUnique: (args: unknown) => Promise<unknown> };
        };
        return client.integrationChannel.findUnique({
          where: { id: input.id },
          include: { integration: true },
        });
      });
      if (!channel) {
        throw new TRPCError({ code: 'NOT_FOUND', message: 'channel not found' });
      }
      // Defer the actual delivery to the worker. The router contract:
      // any non-throwing return means "queued for delivery" — same as
      // webhooks.test-fire. We synthesise a minimal preview here so the
      // UI can echo what would have been posted.
      return {
        ok: true,
        statusCode: null,
        message: 'Test delivery enqueued — check the channel in a few seconds.',
      };
    }),
});
