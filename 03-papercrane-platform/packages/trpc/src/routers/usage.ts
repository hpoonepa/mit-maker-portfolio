/**
 * Usage router — expose seed consumption to the dashboard and programmatic
 * callers. Writes happen in the worker (debit on job completion); the
 * router is read-only.
 *
 * Procedures:
 *   - current                 — back-compat for `UsagePeriodSchema` shape
 *   - history                 — past billing periods
 *   - getCurrentPeriodUsage   — dashboard widget #1 (seed meter)
 *   - getGpuHoursByTool       — dashboard widget #2 (stacked bar by tool)
 *   - getProjection           — linear extrapolation w/ weekend dip override
 *   - getTopUsers             — dashboard widget #3 (top 10 users by spend)
 */
import { z } from 'zod';
import { UsagePeriodSchema } from '@papercrane/types';
import { Prisma } from '@papercrane/db';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Output schemas ─────────────────────────────────────────────────────────

const CurrentPeriodUsageSchema = z.object({
  orgSlug: z.string(),
  orgTier: z.enum(['free', 'pro', 'frontier']),
  periodStart: z.string().datetime(),
  periodEnd: z.string().datetime(),
  seedsIncluded: z.number().int().nonnegative(),
  seedsConsumed: z.number().int().nonnegative(),
  overageSeeds: z.number().int().nonnegative(),
  gpuHours: z.number().nonnegative(),
  pctConsumed: z.number().min(0),
});

const GpuHoursByToolSchema = z.object({
  /** Each item is one day-bucket; `byTool` keys are tool ids. */
  series: z.array(
    z.object({
      day: z.string(),
      byTool: z.record(z.string(), z.number().nonnegative()),
      total: z.number().nonnegative(),
    }),
  ),
  totals: z.record(z.string(), z.number().nonnegative()),
  totalGpuHours: z.number().nonnegative(),
});

const ProjectionSchema = z.object({
  /** Forecast seeds for the full current period. */
  forecastSeeds: z.number().int().nonnegative(),
  /** % of cap the forecast represents (1.0 = 100%). */
  forecastPctOfCap: z.number().min(0),
  /** Daily-ish points used to draw the projection line, including future days. */
  trajectory: z.array(
    z.object({
      day: z.string(),
      actual: z.number().int().nonnegative().nullable(),
      projected: z.number().int().nonnegative(),
    }),
  ),
  /** Set when forecast > 110% of cap. */
  overageWarning: z.boolean(),
  dailyRate: z.number().nonnegative(),
});

const GpuSpendSchema = z.object({
  currentSpendUsd: z.number().nonnegative(),
  capUsd: z.number().nonnegative(),
  remainingUsd: z.number().nonnegative(),
  pctUsed: z.number().nonnegative(),
  recentJobs: z.array(
    z.object({
      id: z.string(),
      jobId: z.string().nullable(),
      tool: z.string(),
      gpuType: z.string(),
      estimatedUsd: z.number().nonnegative(),
      actualUsd: z.number().nonnegative().nullable(),
      secondsActual: z.number().int().nonnegative().nullable(),
      createdAt: z.string().datetime(),
    }),
  ),
});

const TopUsersSchema = z.object({
  items: z.array(
    z.object({
      userId: z.string(),
      name: z.string().nullable(),
      email: z.string().nullable(),
      seedsConsumed: z.number().int().nonnegative(),
      jobCount: z.number().int().nonnegative(),
    }),
  ),
});

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Calendar boundaries of the org's current billing period. We approximate
 * the period as the first → last instant of the current UTC month, which
 * matches the Stripe invoice cadence for the common case.
 */
function currentPeriod(now: Date): { start: Date; end: Date } {
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return { start, end };
}

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function isWeekend(d: Date): boolean {
  const day = d.getUTCDay();
  return day === 0 || day === 6;
}

/**
 * Linear extrapolation from the last 7 calendar days of consumption with a
 * weekend dip override (Sat/Sun get 0.6× weight). Returns the forecast for
 * the full current period plus a per-day trajectory containing both the
 * historical actuals and the forecast tail.
 */
export function computeProjection(args: {
  now: Date;
  periodStart: Date;
  periodEnd: Date;
  /** Day-aggregated consumption inside the current period. Sparse map. */
  byDay: Map<string, number>;
}): z.infer<typeof ProjectionSchema> & { dailyRate: number } {
  const { now, periodStart, periodEnd, byDay } = args;

  // Build last-7-day window (calendar days, ending today inclusive).
  const window: { day: string; date: Date; weight: number; value: number }[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i);
    const key = ymd(d);
    window.push({
      day: key,
      date: d,
      weight: isWeekend(d) ? 0.6 : 1,
      value: byDay.get(key) ?? 0,
    });
  }
  const totalWeight = window.reduce((s, p) => s + p.weight, 0);
  const weightedSum = window.reduce((s, p) => s + p.value * p.weight, 0);
  const dailyRate = totalWeight > 0 ? weightedSum / totalWeight : 0;

  // Build trajectory across the whole period.
  const trajectory: { day: string; actual: number | null; projected: number }[] = [];
  let runningActual = 0;
  let runningProjected = 0;
  for (
    let d = new Date(periodStart);
    d < periodEnd;
    d.setUTCDate(d.getUTCDate() + 1)
  ) {
    const key = ymd(d);
    const dayValue = byDay.get(key) ?? 0;
    const past = d <= now;
    if (past) {
      runningActual += dayValue;
      runningProjected = runningActual;
      trajectory.push({
        day: key,
        actual: Math.round(runningActual),
        projected: Math.round(runningActual),
      });
    } else {
      // Weekend dip applies to forecast tail too (so projections look
      // realistic, not overstated for weekend-heavy months).
      const factor = isWeekend(d) ? 0.6 : 1;
      runningProjected += dailyRate * factor;
      trajectory.push({
        day: key,
        actual: null,
        projected: Math.round(runningProjected),
      });
    }
  }

  const forecastSeeds = Math.max(
    Math.round(runningProjected),
    Math.round(runningActual),
  );

  return {
    forecastSeeds,
    forecastPctOfCap: 0, // filled in by caller (needs cap)
    trajectory,
    overageWarning: false, // filled in by caller
    dailyRate,
  };
}

// ─── Procedures ─────────────────────────────────────────────────────────────

export const usageRouter = router({
  current: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/current',
        tags: ['usage'],
        summary: 'Get the current billing period usage',
        protect: true,
      },
    })
    .input(z.void())
    .output(UsagePeriodSchema)
    .query(async ({ ctx }) => {
      // The `UsagePeriod` mirror table is not yet wired in the schema; the
      // dashboard now reads `getCurrentPeriodUsage` instead. Tolerate the
      // missing table so callers of this legacy procedure get a clean 404.
      try {
        const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
          const client = tx as unknown as {
            usagePeriod?: {
              findFirst?: (args: unknown) => Promise<unknown | null>;
            };
          };
          return client.usagePeriod?.findFirst?.({
            where: { orgSlug: ctx.auth!.orgSlug, isCurrent: true },
          });
        });
        if (!row)
          throw new TRPCError({ code: 'NOT_FOUND', message: 'no current period' });
        return row as z.infer<typeof UsagePeriodSchema>;
      } catch (err) {
        if (err instanceof TRPCError) throw err;
        throw new TRPCError({ code: 'NOT_FOUND', message: 'no current period' });
      }
    }),

  history: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/history',
        tags: ['usage'],
        summary: 'List past billing periods',
        protect: true,
      },
    })
    .input(z.object({ limit: z.number().int().positive().max(24).optional() }))
    .output(z.object({ items: z.array(UsagePeriodSchema) }))
    .query(async ({ ctx, input }) => {
      // Same legacy caveat as `current`: tolerate a missing UsagePeriod table.
      try {
        const items = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              usagePeriod?: {
                findMany?: (args: unknown) => Promise<unknown[]>;
              };
            };
            return (
              (await client.usagePeriod?.findMany?.({
                where: { orgSlug: ctx.auth!.orgSlug },
                orderBy: { periodStart: 'desc' },
                take: input.limit ?? 12,
              })) ?? []
            );
          },
        );
        return { items: items as z.infer<typeof UsagePeriodSchema>[] };
      } catch {
        return { items: [] };
      }
    }),

  /**
   * Widget #1 — current period seed counter (drives the SeedMeter ring).
   * Reads the `Organization` mirror columns first (atomic, gate-checked) and
   * derives gpu-hours from the `Job` table.
   */
  getCurrentPeriodUsage: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/period',
        tags: ['usage'],
        summary: 'Snapshot of seeds + GPU-hours for the current period',
        protect: true,
      },
    })
    .input(z.void())
    .output(CurrentPeriodUsageSchema)
    .query(async ({ ctx }) => {
      const now = ctx.now();
      const { start, end } = currentPeriod(now);

      const result = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          organization: {
            findUnique: (args: unknown) => Promise<{
              slug: string;
              tier: 'free' | 'pro' | 'frontier';
              seedsQuota: number;
              seedsUsed: number;
            } | null>;
          };
          job: {
            aggregate: (args: unknown) => Promise<{
              _sum: { seedsConsumed: number | null };
            }>;
            findMany: (args: unknown) => Promise<
              Array<{ tool: string; seedsConsumed: number; submittedAt: Date }>
            >;
          };
        };

        const org = await client.organization.findUnique({
          where: { id: ctx.auth!.orgId },
        });
        if (!org) {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'org missing' });
        }

        const agg = await client.job.aggregate({
          where: {
            orgId: ctx.auth!.orgId,
            submittedAt: { gte: start, lt: end },
          },
          _sum: { seedsConsumed: true },
        });

        // GPU hours come from completed jobs: seedsConsumed × per-tool seconds.
        // Without a tool-cost table we approximate at a flat 140s/seed (plan
        // 05 §13 RFdiffusion+MPNN+Boltz2 standard). The worker writes the
        // exact GPU cost to UsageSeed.reason today; future iteration should
        // sum that field directly.
        const gpuSeconds = (agg._sum.seedsConsumed ?? 0) * 140;
        return {
          orgSlug: org.slug,
          tier: org.tier,
          seedsConsumed: agg._sum.seedsConsumed ?? 0,
          seedsIncluded: org.seedsQuota,
          gpuHours: gpuSeconds / 3600,
        };
      });

      const overage = Math.max(result.seedsConsumed - result.seedsIncluded, 0);
      const pct =
        result.seedsIncluded > 0 ? result.seedsConsumed / result.seedsIncluded : 0;

      return {
        orgSlug: result.orgSlug,
        orgTier: result.tier,
        periodStart: start.toISOString(),
        periodEnd: end.toISOString(),
        seedsIncluded: result.seedsIncluded,
        seedsConsumed: result.seedsConsumed,
        overageSeeds: overage,
        gpuHours: Number(result.gpuHours.toFixed(2)),
        pctConsumed: pct,
      };
    }),

  /**
   * Widget #2 — daily GPU-hours bucketed by tool for the current period.
   * Returns sparse-by-day series so the chart can render zero-bars where
   * needed.
   */
  getSeedsByTool: protectedProcedure
    .input(z.void())
    .output(z.object({ totals: z.record(z.string(), z.number().int().nonnegative()) }))
    .query(async ({ ctx }) => {
      const { start, end } = currentPeriod(ctx.now());
      const rows = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, tx =>
        tx.job.groupBy({
          by: ['tool'],
          where: { orgId: ctx.auth!.orgId, submittedAt: { gte: start, lt: end }, seedsConsumed: { gt: 0 } },
          _sum: { seedsConsumed: true },
        }),
      );
      return { totals: Object.fromEntries(rows.map(row => [row.tool, row._sum.seedsConsumed ?? 0])) };
    }),

  getGpuHoursByTool: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/gpu-hours',
        tags: ['usage'],
        summary: 'Daily GPU-hours per tool for the current period',
        protect: true,
      },
    })
    .input(z.void())
    .output(GpuHoursByToolSchema)
    .query(async ({ ctx }) => {
      const now = ctx.now();
      const { start, end } = currentPeriod(now);

      const jobs = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          job: {
            findMany: (args: unknown) => Promise<
              Array<{ tool: string; seedsConsumed: number; submittedAt: Date }>
            >;
          };
        };
        return client.job.findMany({
          where: {
            orgId: ctx.auth!.orgId,
            submittedAt: { gte: start, lt: end },
            seedsConsumed: { gt: 0 },
          },
          select: { tool: true, seedsConsumed: true, submittedAt: true },
        });
      });

      // Bucket by day + tool. GPU-hours = seedsConsumed × 140s ÷ 3600.
      const SECONDS_PER_SEED = 140;
      const seriesMap = new Map<string, Record<string, number>>();
      const totals: Record<string, number> = {};
      let totalGpuHours = 0;

      for (let d = new Date(start); d < end; d.setUTCDate(d.getUTCDate() + 1)) {
        seriesMap.set(ymd(d), {});
      }

      for (const job of jobs) {
        const day = ymd(job.submittedAt);
        const hours = (job.seedsConsumed * SECONDS_PER_SEED) / 3600;
        const bucket = seriesMap.get(day) ?? {};
        bucket[job.tool] = (bucket[job.tool] ?? 0) + hours;
        seriesMap.set(day, bucket);
        totals[job.tool] = (totals[job.tool] ?? 0) + hours;
        totalGpuHours += hours;
      }

      const round = (n: number) => Number(n.toFixed(3));
      const series = Array.from(seriesMap.entries()).map(([day, byTool]) => {
        const rounded: Record<string, number> = {};
        let total = 0;
        for (const [tool, hours] of Object.entries(byTool)) {
          rounded[tool] = round(hours);
          total += hours;
        }
        return { day, byTool: rounded, total: round(total) };
      });

      const roundedTotals: Record<string, number> = {};
      for (const [tool, hours] of Object.entries(totals)) {
        roundedTotals[tool] = round(hours);
      }

      return {
        series,
        totals: roundedTotals,
        totalGpuHours: round(totalGpuHours),
      };
    }),

  /**
   * Widget — projection line for the SeedMeter. Linear extrapolation from
   * the last 7 days with a weekend dip override (Sat/Sun get 0.6×). Returns
   * a per-day trajectory containing both historical actuals and the
   * forecast tail.
   */
  getProjection: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/projection',
        tags: ['usage'],
        summary: 'Linear projection of seeds for the current period',
        protect: true,
      },
    })
    .input(z.void())
    .output(ProjectionSchema)
    .query(async ({ ctx }) => {
      const now = ctx.now();
      const { start, end } = currentPeriod(now);

      const data = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          organization: {
            findUnique: (args: unknown) => Promise<{ seedsQuota: number } | null>;
          };
          usageSeed: {
            findMany: (args: unknown) => Promise<
              Array<{ seeds: number; createdAt: Date }>
            >;
          };
        };
        const org = await client.organization.findUnique({
          where: { id: ctx.auth!.orgId },
        });
        const ledger = await client.usageSeed.findMany({
          where: {
            orgId: ctx.auth!.orgId,
            createdAt: { gte: start, lt: end },
            seeds: { gt: 0 },
          },
          select: { seeds: true, createdAt: true },
        });
        return { cap: org?.seedsQuota ?? 0, ledger };
      });

      const byDay = new Map<string, number>();
      for (const row of data.ledger) {
        const key = ymd(row.createdAt);
        byDay.set(key, (byDay.get(key) ?? 0) + row.seeds);
      }

      const projection = computeProjection({
        now,
        periodStart: start,
        periodEnd: end,
        byDay,
      });

      const pct = data.cap > 0 ? projection.forecastSeeds / data.cap : 0;

      return {
        forecastSeeds: projection.forecastSeeds,
        forecastPctOfCap: pct,
        trajectory: projection.trajectory,
        overageWarning: pct > 1.1,
        dailyRate: Number(projection.dailyRate.toFixed(2)),
      };
    }),

  /**
   * GPU spend dashboard — drives the Settings → Spending panel. Returns the
   * org's running total, its cap, percentage used, and the most recent 20
   * GpuSpend ledger rows. Read-only and tolerant of orgs that have never
   * submitted a job (current = 0, no rows).
   */
  getGpuSpend: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/gpu-spend',
        tags: ['usage'],
        summary: 'Current GPU spend vs cap + recent ledger',
        protect: true,
      },
    })
    .input(z.void())
    .output(GpuSpendSchema)
    .query(async ({ ctx }) => {
      const data = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const client = tx as any;
        const org = await client.organization?.findUnique?.({
          where: { id: ctx.auth!.orgId },
          select: { gpuSpendCapUsd: true, gpuSpendUsd: true },
        });
        const rows = (await client.gpuSpend?.findMany?.({
          where: { orgId: ctx.auth!.orgId },
          orderBy: { createdAt: 'desc' },
          take: 20,
        })) ?? [];
        return { org, rows };
      });

      const cap = new Prisma.Decimal(data.org?.gpuSpendCapUsd ?? 50);
      const current = new Prisma.Decimal(data.org?.gpuSpendUsd ?? 0);
      const remaining = Prisma.Decimal.max(cap.sub(current), 0);
      const pct = Number(cap) > 0 ? Number(current) / Number(cap) : 0;

      type Row = {
        id: bigint | string | number;
        jobId: string | null;
        tool: string;
        gpuType: string;
        estimatedUsd: Prisma.Decimal | string | number;
        actualUsd: Prisma.Decimal | string | number | null;
        secondsActual: number | null;
        createdAt: Date;
      };

      return {
        currentSpendUsd: Number(current.toString()),
        capUsd: Number(cap.toString()),
        remainingUsd: Number(remaining.toString()),
        pctUsed: pct,
        recentJobs: (data.rows as Row[]).map((r) => ({
          id: String(r.id),
          jobId: r.jobId,
          tool: r.tool,
          gpuType: r.gpuType,
          estimatedUsd: Number(new Prisma.Decimal(r.estimatedUsd).toString()),
          actualUsd:
            r.actualUsd === null || r.actualUsd === undefined
              ? null
              : Number(new Prisma.Decimal(r.actualUsd).toString()),
          secondsActual: r.secondsActual ?? null,
          createdAt:
            r.createdAt instanceof Date
              ? r.createdAt.toISOString()
              : String(r.createdAt),
        })),
      };
    }),

  /**
   * Widget #3 — top 10 users in the org ranked by seed spend in the current
   * period. Joins `Job → Project.createdBy → User` because the schema only
   * attributes jobs through their project's creator.
   */
  getTopUsers: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/usage/top-users',
        tags: ['usage'],
        summary: 'Top 10 users in org ranked by seed consumption',
        protect: true,
      },
    })
    .input(z.object({ limit: z.number().int().positive().max(50).optional() }))
    .output(TopUsersSchema)
    .query(async ({ ctx, input }) => {
      const now = ctx.now();
      const { start, end } = currentPeriod(now);
      const limit = input.limit ?? 10;

      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          job: {
            findMany: (args: unknown) => Promise<
              Array<{
                seedsConsumed: number;
                project: { creator: { id: string; name: string | null; email: string } | null } | null;
              }>
            >;
          };
        };
        return client.job.findMany({
          where: {
            orgId: ctx.auth!.orgId,
            submittedAt: { gte: start, lt: end },
            seedsConsumed: { gt: 0 },
          },
          select: {
            seedsConsumed: true,
            project: {
              select: {
                creator: { select: { id: true, name: true, email: true } },
              },
            },
          },
        });
      });

      // Aggregate in memory: small N (one org's monthly jobs) and Prisma
      // groupBy over a chained relation isn't straightforward.
      const agg = new Map<
        string,
        { name: string | null; email: string | null; seeds: number; jobs: number }
      >();
      for (const job of items) {
        const u = job.project?.creator;
        if (!u) continue;
        const cur = agg.get(u.id) ?? {
          name: u.name,
          email: u.email,
          seeds: 0,
          jobs: 0,
        };
        cur.seeds += job.seedsConsumed;
        cur.jobs += 1;
        agg.set(u.id, cur);
      }

      const ranked = Array.from(agg.entries())
        .map(([userId, v]) => ({
          userId,
          name: v.name,
          email: v.email,
          seedsConsumed: v.seeds,
          jobCount: v.jobs,
        }))
        .sort((a, b) => b.seedsConsumed - a.seedsConsumed)
        .slice(0, limit);

      return { items: ranked };
    }),
});
