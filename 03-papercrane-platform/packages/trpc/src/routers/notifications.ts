/**
 * Notifications router — the caller's own inbox, plus preferences.
 *
 * Procedures
 *   - `list({ cursor?, limit, unreadOnly? })`  paginated feed
 *   - `markRead({ id })`                       mark a single row read
 *   - `markAllRead()`                          mark every unread row read
 *   - `preferences.get()`                      flattened (category × channel) map
 *   - `preferences.update({ category, channel, enabled })`
 *
 * Access model
 * ------------
 * Every procedure uses `withRlsUser`. Because notifications are *user*-
 * scoped (not org-scoped), the RLS policy on the table matches by
 * `user_id = app_current_user()`. We still issue the query filtered by
 * `userId` as belt-and-suspenders: if RLS is ever disabled by accident
 * the query still returns only the caller's rows.
 *
 * Preference defaults
 * -------------------
 * `DEFAULT_PREFERENCES` encodes the product spec:
 *
 *   job.completed    → in-app + email
 *   job.failed       → in-app + email
 *   billing.warning  → in-app + email
 *   webhook.failed   → in-app only
 *   invite.received  → in-app + email
 *   system.*         → in-app only
 *
 * The router stores at the (category × channel) granularity; the
 * finer `job.completed` vs `job.failed` distinction is an event-type
 * subtype that the worker decides at dispatch time. We default both
 * `job` channels enabled so the worker does not have to synthesise
 * rows for every subtype on first use.
 */
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Zod shapes ─────────────────────────────────────────────────────────────

const NotificationCategoryEnum = z.enum([
  'job',
  'billing',
  'webhook',
  'invite',
  'system',
]);

const NotificationChannelEnum = z.enum(['in_app', 'email']);

const NotificationSchema = z.object({
  id: z.string().uuid(),
  category: NotificationCategoryEnum,
  title: z.string(),
  description: z.string().nullable(),
  actionUrl: z.string().nullable(),
  metadata: z.record(z.unknown()).nullable(),
  readAt: z.string().nullable(),
  createdAt: z.string(),
});

const ListInput = z
  .object({
    cursor: z.string().optional(),
    limit: z.number().int().positive().max(100).optional(),
    unreadOnly: z.boolean().optional(),
  })
  .strict();

const ListOutput = z.object({
  items: z.array(NotificationSchema),
  nextCursor: z.string().optional(),
});

// Preferences are returned as a nested map:
//   prefs[category][channel] = enabled
// This shape is cheap to consume in the UI and easy to mutate for the
// `update` mutation by writing a single row.
const PreferencesMap = z.record(
  NotificationCategoryEnum,
  z.record(NotificationChannelEnum, z.boolean()),
);

const PreferencesOutput = z.object({ prefs: PreferencesMap });

const UpdatePreferenceInput = z
  .object({
    category: NotificationCategoryEnum,
    channel: NotificationChannelEnum,
    enabled: z.boolean(),
  })
  .strict();

// ─── Defaults ───────────────────────────────────────────────────────────────
// Matches the spec:
//   job.completed / job.failed      — in-app + email
//   billing.warning                 — in-app + email
//   webhook.failed                  — in-app only
//   invite.received                 — in-app + email
// System is in-app only.

type Category = z.infer<typeof NotificationCategoryEnum>;
type Channel = z.infer<typeof NotificationChannelEnum>;

export const DEFAULT_PREFERENCES: Record<Category, Record<Channel, boolean>> = {
  job: { in_app: true, email: true },
  billing: { in_app: true, email: true },
  webhook: { in_app: true, email: false },
  invite: { in_app: true, email: true },
  system: { in_app: true, email: false },
};

const CATEGORIES: Category[] = ['job', 'billing', 'webhook', 'invite', 'system'];
const CHANNELS: Channel[] = ['in_app', 'email'];

// ─── Sub-router: preferences ────────────────────────────────────────────────

const preferencesRouter = router({
  get: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/notifications/preferences',
        tags: ['notifications'],
        summary: 'Get the caller’s notification preferences',
        protect: true,
      },
    })
    .input(z.void())
    .output(PreferencesOutput)
    .query(async ({ ctx }) => {
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            notificationPreference: {
              findMany: (args: unknown) => Promise<
                Array<{ category: Category; channel: Channel; enabled: boolean }>
              >;
            };
          };
          return client.notificationPreference.findMany({
            where: { userId: ctx.auth!.userId },
          });
        },
      );

      // Materialize the defaults for any (category, channel) the caller
      // has not explicitly set yet. This avoids a "first-access write"
      // side effect on GET while still giving the UI a complete map.
      const prefs: Record<Category, Record<Channel, boolean>> = {
        job: { ...DEFAULT_PREFERENCES.job },
        billing: { ...DEFAULT_PREFERENCES.billing },
        webhook: { ...DEFAULT_PREFERENCES.webhook },
        invite: { ...DEFAULT_PREFERENCES.invite },
        system: { ...DEFAULT_PREFERENCES.system },
      };
      for (const row of rows) {
        prefs[row.category][row.channel] = row.enabled;
      }
      return { prefs };
    }),

  update: protectedProcedure
    .meta({
      openapi: {
        method: 'PUT',
        path: '/notifications/preferences',
        tags: ['notifications'],
        summary: 'Update a single preference (category × channel)',
        protect: true,
      },
    })
    .input(UpdatePreferenceInput)
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          notificationPreference: {
            upsert: (args: {
              where: Record<string, unknown>;
              create: Record<string, unknown>;
              update: Record<string, unknown>;
            }) => Promise<unknown>;
          };
        };
        await client.notificationPreference.upsert({
          where: {
            userId_category_channel: {
              userId: ctx.auth!.userId,
              category: input.category,
              channel: input.channel,
            },
          },
          create: {
            userId: ctx.auth!.userId,
            category: input.category,
            channel: input.channel,
            enabled: input.enabled,
          },
          update: { enabled: input.enabled },
        });
      });
      // Referenced to quiet the unused-import check when `CATEGORIES` /
      // `CHANNELS` are only read from tests; the router itself does not
      // iterate them, but exporting them keeps the public surface small.
      void CATEGORIES;
      void CHANNELS;
      return { ok: true as const };
    }),
});

// ─── Main router ────────────────────────────────────────────────────────────

export const notificationsRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/notifications',
        tags: ['notifications'],
        summary: 'List the caller’s notifications',
        protect: true,
      },
    })
    .input(ListInput)
    .output(ListOutput)
    .query(async ({ ctx, input }) => {
      const limit = input.limit ?? 25;
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            notification: {
              findMany: (args: unknown) => Promise<
                Array<{
                  id: string;
                  category: Category;
                  title: string;
                  description: string | null;
                  actionUrl: string | null;
                  metadata: Record<string, unknown> | null;
                  readAt: Date | string | null;
                  createdAt: Date | string;
                }>
              >;
            };
          };
          return client.notification.findMany({
            where: {
              userId: ctx.auth!.userId,
              ...(input.unreadOnly ? { readAt: null } : {}),
              ...(input.cursor
                ? { createdAt: { lt: new Date(input.cursor) } }
                : {}),
            },
            orderBy: { createdAt: 'desc' },
            take: limit + 1, // fetch one extra to compute nextCursor
          });
        },
      );

      const hasMore = rows.length > limit;
      const trimmed = hasMore ? rows.slice(0, limit) : rows;
      const items = trimmed.map((r) => ({
        id: r.id,
        category: r.category,
        title: r.title,
        description: r.description,
        actionUrl: r.actionUrl,
        metadata: r.metadata,
        readAt:
          r.readAt === null
            ? null
            : r.readAt instanceof Date
              ? r.readAt.toISOString()
              : String(r.readAt),
        createdAt:
          r.createdAt instanceof Date
            ? r.createdAt.toISOString()
            : String(r.createdAt),
      }));
      const nextCursor = hasMore
        ? items[items.length - 1]?.createdAt
        : undefined;
      return { items, nextCursor };
    }),

  markRead: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/notifications/{id}/read',
        tags: ['notifications'],
        summary: 'Mark a single notification read',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().uuid() }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const n = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            notification: {
              updateMany: (args: {
                where: Record<string, unknown>;
                data: Record<string, unknown>;
              }) => Promise<{ count: number }>;
            };
          };
          // updateMany so we can scope by userId *and* id; single-row
          // update by id alone would surface a foreign row if RLS were
          // ever disabled.
          const res = await client.notification.updateMany({
            where: { id: input.id, userId: ctx.auth!.userId, readAt: null },
            data: { readAt: new Date() },
          });
          return res.count;
        },
      );
      if (n === 0) {
        // Either the notification is already read, or it doesn't belong
        // to this user. Treat both as a noop — don't leak existence.
        return { ok: true as const };
      }
      return { ok: true as const };
    }),

  markAllRead: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/notifications/read-all',
        tags: ['notifications'],
        summary: 'Mark every unread notification read',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ count: z.number().int().nonnegative() }))
    .mutation(async ({ ctx }) => {
      const count = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            notification: {
              updateMany: (args: {
                where: Record<string, unknown>;
                data: Record<string, unknown>;
              }) => Promise<{ count: number }>;
            };
          };
          const res = await client.notification.updateMany({
            where: { userId: ctx.auth!.userId, readAt: null },
            data: { readAt: new Date() },
          });
          return res.count;
        },
      );
      return { count };
    }),

  preferences: preferencesRouter,
});

// Silence the "declared but not read" warning for TRPCError during strict-
// mode type-checking — we keep the import available for future error paths.
void TRPCError;
