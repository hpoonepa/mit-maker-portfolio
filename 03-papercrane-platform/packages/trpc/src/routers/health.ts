/**
 * Health router — unauthenticated liveness check. The API exposes `ping` at
 * GET /v1/health for load balancers and monitoring. `check` is a richer
 * dashboard probe that reports DB and Supabase connectivity.
 */
import { z } from 'zod';
import { router, publicProcedure } from '../trpc.js';

export const healthRouter = router({
  ping: publicProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/health',
        tags: ['health'],
        summary: 'Liveness probe',
      },
    })
    .input(z.void())
    .output(z.object({ ok: z.literal(true), at: z.string().datetime() }))
    .query(({ ctx }) => ({ ok: true as const, at: ctx.now().toISOString() })),

  check: publicProcedure
    .output(
      z.object({
        ok: z.boolean(),
        db: z.boolean(),
        supabase: z.boolean(),
        version: z.string(),
        ts: z.string(),
      }),
    )
    .query(async ({ ctx }) => {
      let db = false;
      try {
        await ctx.prisma.$queryRaw`SELECT 1`;
        db = true;
      } catch {
        // DB unreachable — surface in `db: false` rather than throwing so
        // the dashboard can render a degraded state.
      }
      const supabase = !!process.env.NEXT_PUBLIC_SUPABASE_URL;
      return {
        ok: db,
        db,
        supabase,
        version: process.env.npm_package_version ?? 'dev',
        ts: ctx.now().toISOString(),
      };
    }),
});
