/**
 * Dashboard router — read-only aggregations that power the workspace
 * dashboard widgets. Existing per-domain routers (`usage`, `audit`,
 * `projects`) cover most needs already; this router adds two thin
 * aggregations the dashboard renders directly:
 *
 *   - getRecentActivity — last N audit log entries (newest first)
 *   - getTopProjects    — top N most-active projects in the current period
 *
 * All queries are org-scoped via `withRlsUser` so RLS does the gating; we
 * still pass `orgId` in `where` clauses so Postgres uses the
 * `(org_id, created_at DESC)` covering indexes without leaning on the
 * policy predicate.
 */
import { z } from 'zod';
import { router, publicProcedure } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const RecentActivitySchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      action: z.string(),
      resourceType: z.string().nullable(),
      resourceId: z.string().nullable(),
      createdAt: z.date(),
      actorName: z.string().nullable(),
      actorEmail: z.string().nullable(),
    }),
  ),
});

const TopProjectsSchema = z.object({
  items: z.array(
    z.object({
      projectId: z.string(),
      name: z.string(),
      slug: z.string(),
      jobCount: z.number().int().nonnegative(),
      seedsConsumed: z.number().int().nonnegative(),
      lastActivity: z.date().nullable(),
    }),
  ),
});

function currentPeriod(now: Date): { start: Date; end: Date } {
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return { start, end };
}

export const dashboardRouter = router({
  /**
   * Last N audit log rows for the org, newest first. Uses the same shape
   * as `audit.list` but trimmed to the fields the activity feed needs.
   */
  getRecentActivity: protectedProcedure
    .input(z.object({ limit: z.number().int().positive().max(50).optional() }))
    .output(RecentActivitySchema)
    .query(async ({ ctx, input }) => {
      const limit = input.limit ?? 10;
      const rows = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          auditLog: {
            findMany: (args: unknown) => Promise<
              Array<{
                id: string;
                action: string;
                resourceType: string | null;
                resourceId: string | null;
                createdAt: Date;
                user: { name: string | null; email: string } | null;
              }>
            >;
          };
        };
        return client.auditLog.findMany({
          where: { orgId: ctx.auth!.orgId },
          orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
          take: limit,
          include: { user: { select: { name: true, email: true } } },
        });
      });
      return {
        items: rows.map((r) => ({
          id: r.id,
          action: r.action,
          resourceType: r.resourceType,
          resourceId: r.resourceId,
          createdAt: r.createdAt,
          actorName: r.user?.name ?? null,
          actorEmail: r.user?.email ?? null,
        })),
      };
    }),

  /**
   * Top N projects in the org ranked by jobs submitted in the current
   * billing period. We aggregate in memory because Prisma `groupBy` over
   * a chained relation isn't first-class; N is small (one org's projects).
   */
  getTopProjects: protectedProcedure
    .input(z.object({ limit: z.number().int().positive().max(20).optional() }))
    .output(TopProjectsSchema)
    .query(async ({ ctx, input }) => {
      const now = ctx.now();
      const { start, end } = currentPeriod(now);
      const limit = input.limit ?? 5;

      const data = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          job: {
            findMany: (args: unknown) => Promise<
              Array<{
                projectId: string | null;
                seedsConsumed: number;
                submittedAt: Date;
                project: { id: string; name: string; slug: string } | null;
              }>
            >;
          };
        };
        return client.job.findMany({
          where: {
            orgId: ctx.auth!.orgId,
            submittedAt: { gte: start, lt: end },
            projectId: { not: null },
          },
          select: {
            projectId: true,
            seedsConsumed: true,
            submittedAt: true,
            project: { select: { id: true, name: true, slug: true } },
          },
        });
      });

      const agg = new Map<
        string,
        {
          name: string;
          slug: string;
          jobs: number;
          seeds: number;
          last: Date | null;
        }
      >();
      for (const job of data) {
        const p = job.project;
        if (!p) continue;
        const cur = agg.get(p.id) ?? {
          name: p.name,
          slug: p.slug,
          jobs: 0,
          seeds: 0,
          last: null,
        };
        cur.jobs += 1;
        cur.seeds += job.seedsConsumed;
        if (!cur.last || job.submittedAt > cur.last) cur.last = job.submittedAt;
        agg.set(p.id, cur);
      }

      const ranked = Array.from(agg.entries())
        .map(([projectId, v]) => ({
          projectId,
          name: v.name,
          slug: v.slug,
          jobCount: v.jobs,
          seedsConsumed: v.seeds,
          lastActivity: v.last,
        }))
        .sort((a, b) => b.jobCount - a.jobCount || b.seedsConsumed - a.seedsConsumed)
        .slice(0, limit);

      return { items: ranked };
    }),
});
