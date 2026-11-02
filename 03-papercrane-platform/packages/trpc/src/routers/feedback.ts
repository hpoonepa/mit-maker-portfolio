/**
 * Feedback router — beta-tester feedback widget submissions.
 *
 * Procedures
 *   - submit({ category, rating?, body, pageUrl?, userAgent?, screenshotKey?, metadata? })
 *       Authenticated submission from the in-app widget. Stamps orgId/userId
 *       from the resolved auth context.
 *
 *   - list({ status?, category?, since?, limit?, cursor? })
 *       Admin-only feedback inbox. Org owners/admins see only their org's
 *       rows; the route does not currently expose a super-admin "see all"
 *       mode (there is no super-admin role in the auth context yet — the
 *       admin app for that lives behind a separate service-role console).
 *
 *   - updateStatus({ id, status })
 *       Admin-only. Allowed transitions: new → reviewing → addressed/won_t_fix.
 *
 * Access model
 * ------------
 * - submit  — any authenticated principal (user or API key); RLS is bypassed
 *             via service role on the API server, so we explicitly stamp
 *             orgId/userId from `ctx.auth`.
 * - list    — gated on the caller being `owner` or `admin` of their org.
 * - update  — same gating as list.
 */
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Zod shapes ─────────────────────────────────────────────────────────────

const FeedbackCategoryEnum = z.enum([
  'bug',
  'feature',
  'improvement',
  'praise',
  'other',
]);

const FeedbackStatusEnum = z.enum([
  'new',
  'reviewing',
  'addressed',
  'won_t_fix',
]);

const SubmitInput = z
  .object({
    category: FeedbackCategoryEnum.default('other'),
    rating: z.number().int().min(0).max(10).optional(),
    body: z.string().trim().min(1).max(2000),
    pageUrl: z.string().url().max(2048).optional(),
    userAgent: z.string().max(512).optional(),
    screenshotKey: z.string().max(512).optional(),
    metadata: z.record(z.unknown()).optional(),
  })
  .strict();

const SubmitOutput = z.object({
  id: z.string(),
  ok: z.literal(true),
});

const ListInput = z
  .object({
    status: FeedbackStatusEnum.optional(),
    category: FeedbackCategoryEnum.optional(),
    since: z.string().datetime().optional(),
    limit: z.number().int().positive().max(100).default(50),
    cursor: z.string().optional(),
  })
  .strict();

const FeedbackRow = z.object({
  id: z.string(),
  orgId: z.string().nullable(),
  userId: z.string().nullable(),
  category: FeedbackCategoryEnum,
  rating: z.number().int().nullable(),
  body: z.string(),
  pageUrl: z.string().nullable(),
  userAgent: z.string().nullable(),
  screenshotKey: z.string().nullable(),
  metadata: z.record(z.unknown()).nullable(),
  status: z.string(),
  createdAt: z.string(),
});

const ListOutput = z.object({
  items: z.array(FeedbackRow),
  nextCursor: z.string().optional(),
});

const UpdateStatusInput = z
  .object({
    id: z.string().min(1),
    status: FeedbackStatusEnum,
  })
  .strict();

// ─── Helpers ────────────────────────────────────────────────────────────────

type AdminClient = {
  orgMember: {
    findUnique: (args: unknown) => Promise<{ role: string } | null>;
  };
  feedback: {
    create: (args: { data: Record<string, unknown> }) => Promise<{ id: string }>;
    findMany: (args: unknown) => Promise<
      Array<{
        id: string;
        orgId: string | null;
        userId: string | null;
        category: 'bug' | 'feature' | 'improvement' | 'praise' | 'other';
        rating: number | null;
        body: string;
        pageUrl: string | null;
        userAgent: string | null;
        screenshotKey: string | null;
        metadata: Record<string, unknown> | null;
        status: string;
        createdAt: Date;
      }>
    >;
    update: (args: {
      where: Record<string, unknown>;
      data: Record<string, unknown>;
    }) => Promise<unknown>;
    findUnique: (args: unknown) => Promise<{ orgId: string | null } | null>;
  };
};

async function assertOrgAdmin(
  client: AdminClient,
  orgId: string,
  userId: string,
): Promise<void> {
  const me = await client.orgMember.findUnique({
    where: { orgId_userId: { orgId, userId } },
  });
  if (!me) {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'not a member of this org',
    });
  }
  if (me.role !== 'owner' && me.role !== 'admin') {
    throw new TRPCError({
      code: 'FORBIDDEN',
      message: 'only owners and admins can view feedback',
    });
  }
}

// ─── Router ─────────────────────────────────────────────────────────────────

export const feedbackRouter = router({
  molecularDynamicsWaitlist: protectedProcedure
    .input(z.void())
    .output(z.object({ joined: z.boolean() }))
    .query(async ({ ctx }) => {
      const auth = ctx.auth!;
      return ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        const rows = await (tx as unknown as AdminClient).feedback.findMany({
          where: {
            userId: auth.userId,
            orgId: auth.orgId,
            metadata: { path: ['waitlist'], equals: 'molecular-dynamics' },
          },
          take: 1,
        });
        return { joined: rows.length > 0 };
      });
    }),

  joinMolecularDynamicsWaitlist: protectedProcedure
    .input(z.void())
    .output(z.object({ joined: z.literal(true) }))
    .mutation(async ({ ctx }) => {
      const auth = ctx.auth!;
      return ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        const feedback = (tx as unknown as AdminClient).feedback;
        const rows = await feedback.findMany({
          where: {
            userId: auth.userId,
            orgId: auth.orgId,
            metadata: { path: ['waitlist'], equals: 'molecular-dynamics' },
          },
          take: 1,
        });
        if (!rows.length) await feedback.create({ data: {
          orgId: auth.orgId,
          userId: auth.userId,
          category: 'feature',
          body: 'Please add me to the molecular dynamics model waitlist.',
          metadata: { waitlist: 'molecular-dynamics' },
          status: 'new',
        } });
        return { joined: true as const };
      });
    }),

  submit: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/feedback',
        tags: ['feedback'],
        summary: 'Submit user feedback from the in-app widget',
        protect: true,
      },
    })
    .input(SubmitInput)
    .output(SubmitOutput)
    .mutation(async ({ ctx, input }) => {
      const auth = ctx.auth!;
      const created = await ctx.withRlsUser(
        ctx.prisma,
        auth.userId,
        async (tx) => {
          const client = tx as unknown as AdminClient;
          return client.feedback.create({
            data: {
              orgId: auth.orgId,
              userId: auth.userId,
              category: input.category,
              rating: input.rating ?? null,
              body: input.body,
              pageUrl: input.pageUrl ?? null,
              userAgent: input.userAgent ?? null,
              screenshotKey: input.screenshotKey ?? null,
              metadata: (input.metadata ?? null) as unknown as object | null,
              status: 'new',
            },
          });
        },
      );
      return { id: created.id, ok: true as const };
    }),

  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/feedback',
        tags: ['feedback'],
        summary: 'List feedback for the caller’s org (admin only)',
        protect: true,
      },
    })
    .input(ListInput)
    .output(ListOutput)
    .query(async ({ ctx, input }) => {
      const auth = ctx.auth!;
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        auth.userId,
        async (tx) => {
          const client = tx as unknown as AdminClient;
          await assertOrgAdmin(client, auth.orgId, auth.userId);

          const where: Record<string, unknown> = { orgId: auth.orgId };
          if (input.status) where.status = input.status;
          if (input.category) where.category = input.category;
          if (input.since) where.createdAt = { gte: new Date(input.since) };

          return client.feedback.findMany({
            where,
            orderBy: { createdAt: 'desc' },
            take: input.limit + 1,
            ...(input.cursor ? { cursor: { id: input.cursor }, skip: 1 } : {}),
          });
        },
      );

      let nextCursor: string | undefined;
      if (rows.length > input.limit) {
        const nextRow = rows.pop();
        nextCursor = nextRow?.id;
      }

      return {
        items: rows.map((r) => ({
          id: r.id,
          orgId: r.orgId,
          userId: r.userId,
          category: r.category,
          rating: r.rating,
          body: r.body,
          pageUrl: r.pageUrl,
          userAgent: r.userAgent,
          screenshotKey: r.screenshotKey,
          metadata: r.metadata,
          status: r.status,
          createdAt: r.createdAt.toISOString(),
        })),
        ...(nextCursor ? { nextCursor } : {}),
      };
    }),

  updateStatus: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/feedback/{id}',
        tags: ['feedback'],
        summary: 'Update feedback triage status (admin only)',
        protect: true,
      },
    })
    .input(UpdateStatusInput)
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const auth = ctx.auth!;
      await ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        const client = tx as unknown as AdminClient;
        await assertOrgAdmin(client, auth.orgId, auth.userId);

        const existing = await client.feedback.findUnique({
          where: { id: input.id },
        });
        if (!existing || existing.orgId !== auth.orgId) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'feedback not found',
          });
        }
        await client.feedback.update({
          where: { id: input.id },
          data: { status: input.status },
        });
      });
      return { ok: true as const };
    }),
});
