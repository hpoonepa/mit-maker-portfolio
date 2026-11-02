/**
 * Designs router — read-only access to the designs produced by a job.
 * `get` returns the row plus a short-lived presigned GET URL for the
 * predicted-structure artifact; the API caller downloads straight from R2.
 */
import { z } from 'zod';
import { DesignResultSchema, normaliseDesignProvenance } from '@papercrane/types';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth, requireScope } from '../middleware/auth.js';
import {
  MetaScoreDetailSchema,
  MetaScoreSummarySchema,
  metaScoreSummary,
  scoreDesignWithLlmPrior,
} from '../scoring/llmMetaScorer.js';
import {
  CandidateDecisionReportSchema,
  buildCandidateDecisionReport,
} from '../reporting/candidateDecisionReport.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const PlatformDesignResultSchema = DesignResultSchema.extend({
  sequence: z.string().min(1).optional(),
  length: z.number().int().positive().optional(),
  metrics: z.record(z.string(), z.unknown()),
  provenance: z.preprocess(normaliseDesignProvenance, z.enum(['real', 'synthetic', 'stub', 'unknown'])),
});

// The DB row carries columns that aren't part of the public DesignResult
// wire shape (orgId, rank, …). We surface the useful ones and `.passthrough()`
// the rest so a real Prisma row never trips the output validator. Previously
// this was `.strict()`, which threw on every real row and made the presigned
// `structureUrl` permanently unreachable.
const GetOutput = PlatformDesignResultSchema.extend({
  structureUrl: z.string().url().optional(),
  structureExpiresInSec: z.number().int().positive().optional(),
  tool: z.string().optional(),
  jobId: z.string().uuid().optional(),
  orgId: z.string().uuid().optional(),
  rank: z.number().int().nullable().optional(),
  metaScore: MetaScoreDetailSchema,
}).passthrough();

const DesignWithToolSchema = PlatformDesignResultSchema.extend({
  tool: z.string().optional(),
  rank: z.number().int().nullable().optional(),
  metaScore: MetaScoreSummarySchema,
}).passthrough();

const ScoredDesignSchema = PlatformDesignResultSchema.extend({
  metaScore: MetaScoreSummarySchema,
  structureUrl: z.string().url().optional(),
  structureExpiresInSec: z.number().int().positive().optional(),
}).passthrough();

type JobScoringContext = {
  tool?: string | null;
  projectId?: string | null;
  params?: unknown;
  target?: { name?: string | null; pdbId?: string | null } | null;
};

function scoringTarget(job?: JobScoringContext | null): {
  targetName: string | null;
  pdbId: string | null;
} {
  const params =
    job?.params && typeof job.params === 'object'
      ? (job.params as Record<string, unknown>)
      : null;
  const requestPdb = typeof params?.targetPdb === 'string' ? params.targetPdb.trim() : '';
  return {
    targetName: job?.target?.name ?? null,
    pdbId:
      job?.target?.pdbId ??
      (/^[A-Za-z0-9]{4}$/.test(requestPdb) ? requestPdb.toUpperCase() : null),
  };
}

function metricsFrom(row: Record<string, unknown>): Record<string, unknown> {
  return row.metrics && typeof row.metrics === 'object'
    ? (row.metrics as Record<string, unknown>)
    : {};
}

function designWire(row: Record<string, unknown>): Record<string, unknown> {
  const metrics = metricsFrom(row);
  const sequence =
    typeof row.sequence === 'string'
      ? row.sequence
      : typeof metrics.sequence === 'string'
        ? metrics.sequence
        : undefined;
  const metricLength =
    typeof metrics.length === 'number' && Number.isInteger(metrics.length) && metrics.length > 0
      ? metrics.length
      : undefined;
  const length =
    typeof row.length === 'number' && Number.isInteger(row.length) && row.length > 0
      ? row.length
      : metricLength ?? sequence?.length;
  const createdAt =
    row.createdAt instanceof Date ? row.createdAt.toISOString() : row.createdAt;
  return {
    ...row,
    provenance: normaliseDesignProvenance(row.provenance),
    metrics,
    ...(sequence ? { sequence } : {}),
    ...(length ? { length } : {}),
    createdAt,
  };
}

export const designsRouter = router({
  /** Stable, unscored enumeration for archives; never capped to the first UI page. */
  exportPage: protectedProcedure
    .use(requireScope('designs:read'))
    .input(z.object({
      scope: z.enum(['job', 'project']),
      id: z.string().uuid(),
      snapshotAt: z.string().datetime(),
      cursor: z.string().uuid().optional(),
      limit: z.number().int().min(1).max(500).default(500),
    }).strict())
    .output(z.object({
      items: z.array(z.object({
        id: z.string().uuid(),
        seed: z.number().int().nonnegative(),
        provenance: z.string(),
      })),
      nextCursor: z.string().uuid().nullable(),
    }))
    .query(async ({ ctx, input }) => {
      const rows = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, (tx) =>
        tx.design.findMany({
          where: {
            orgId: ctx.auth.orgId,
            ...(input.scope === 'job'
              ? { jobId: input.id }
              : { job: { projectId: input.id } }),
            createdAt: { lte: new Date(input.snapshotAt) },
            ...(input.cursor ? { id: { gt: input.cursor } } : {}),
          },
          select: { id: true, seed: true, provenance: true },
          orderBy: { id: 'asc' },
          take: input.limit + 1,
        }),
      );
      const page = rows.slice(0, input.limit);
      return {
        items: page.map((row) => ({ ...row, provenance: normaliseDesignProvenance(row.provenance) })),
        nextCursor: rows.length > input.limit ? page[page.length - 1]!.id : null,
      };
    }),

  listByJob: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/jobs/{jobId}/designs',
        tags: ['designs'],
        summary: 'List designs produced by a job',
        protect: true,
      },
    })
    .input(
      z.object({
        jobId: z.string().min(1),
        limit: z.number().int().positive().max(500).optional(),
        includeStructureUrls: z.boolean().optional(),
      }),
    )
    .output(z.object({ items: z.array(ScoredDesignSchema) }))
    .query(async ({ ctx, input }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          design: { findMany: (args: unknown) => Promise<Record<string, unknown>[]> };
        };
        return client.design.findMany({
          where: { jobId: input.jobId, orgId: ctx.auth!.orgId },
          include: {
            job: {
              select: {
                params: true,
                target: { select: { name: true, pdbId: true } },
              },
            },
          },
          orderBy: { createdAt: 'asc' },
          take: input.limit ?? 200,
        });
      });
      return {
        items: await Promise.all(items.map(async (row) => {
          const { job, ...design } = row;
          const target = scoringTarget(job as JobScoringContext | null);
          const detail = scoreDesignWithLlmPrior({
            metrics: metricsFrom(row),
            ...target,
          });
          const artifactKey =
            typeof design.artifactKey === 'string' ? design.artifactKey : null;
          const structureUrl =
            input.includeStructureUrls && artifactKey
              ? await ctx.presignGet(artifactKey, 15 * 60)
              : undefined;
          return {
            ...designWire(design),
            metaScore: metaScoreSummary(detail),
            ...(structureUrl
              ? { structureUrl, structureExpiresInSec: 15 * 60 }
              : {}),
          };
        })) as z.infer<typeof ScoredDesignSchema>[],
      };
    }),

  /**
   * Project-scoped list. Joins designs to their parent job so the UI can
   * filter by tool (e.g. only RFdiffusion designs in this project) and so
   * the client knows which job each design belongs to without a second
   * round trip. Filters apply server-side; the client does the final sort.
   */
  listByProject: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/projects/{projectId}/designs',
        tags: ['designs'],
        summary: 'List designs across all jobs in a project',
        protect: true,
      },
    })
    .input(
      z
        .object({
          projectId: z.string().min(1),
          tool: z.string().optional(),
          limit: z.number().int().positive().max(500).optional(),
        })
        .strict(),
    )
    .output(z.object({ items: z.array(DesignWithToolSchema) }))
    .query(async ({ ctx, input }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          design: {
            findMany: (args: unknown) => Promise<
              Array<
                Record<string, unknown> & {
                  job?: JobScoringContext | null;
                }
              >
            >;
          };
        };
        return client.design.findMany({
          where: {
            orgId: ctx.auth!.orgId,
            job: {
              projectId: input.projectId,
              ...(input.tool ? { tool: input.tool } : {}),
            },
          },
          include: {
            job: {
              select: {
                tool: true,
                projectId: true,
                params: true,
                target: { select: { name: true, pdbId: true } },
              },
            },
          },
          orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
          take: input.limit ?? 200,
        });
      });

      const flattened = items.map((row) => {
        const { job, ...rest } = row;
        const target = scoringTarget(job);
        const detail = scoreDesignWithLlmPrior({
          metrics: metricsFrom(row),
          ...target,
        });
        return {
          ...designWire(rest),
          tool: job?.tool ?? undefined,
          metaScore: metaScoreSummary(detail),
        } as z.infer<
          typeof DesignWithToolSchema
        >;
      });
      return { items: flattened };
    }),

  decisionReport: protectedProcedure
    .input(
      z
        .object({
          jobId: z.string().min(1),
          limit: z.number().int().positive().max(500).optional(),
        })
        .strict(),
    )
    .output(CandidateDecisionReportSchema)
    .query(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          job: { findFirst: (args: unknown) => Promise<Record<string, unknown> | null> };
        };
        return client.job.findFirst({
          where: { id: input.jobId, orgId: ctx.auth!.orgId },
          include: {
            target: { select: { name: true, pdbId: true } },
            designs: {
              orderBy: [{ rank: 'asc' }, { seed: 'asc' }],
              take: input.limit ?? 500,
            },
          },
        });
      });
      if (!row) throw new TRPCError({ code: 'NOT_FOUND', message: 'job not found' });
      return buildCandidateDecisionReport({
        job: row as never,
        designs: (Array.isArray(row.designs) ? row.designs : []) as never[],
      });
    }),

  get: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/designs/{id}',
        tags: ['designs'],
        summary: 'Get a design with a presigned URL for its structure',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(GetOutput)
    .query(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          design: {
            findFirst: (args: unknown) => Promise<
              | (Record<string, unknown> & {
                  jobId?: string;
                  job?: JobScoringContext | null;
                })
              | null
            >;
          };
        };
        return client.design.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
          include: {
            job: {
              select: {
                tool: true,
                projectId: true,
                params: true,
                target: { select: { name: true, pdbId: true } },
              },
            },
          },
        });
      });
      if (!row) throw new TRPCError({ code: 'NOT_FOUND', message: 'design not found' });
      const { job, ...rest } = row;
      const typed = designWire(rest) as z.infer<typeof PlatformDesignResultSchema> & {
        artifactKey?: string;
      };
      let structureUrl: string | undefined;
      // The structure object key lives in the `artifact_key` column → Prisma
      // `artifactKey`. Presign it so the in-app Mol* viewer and download links
      // resolve to the real R2 bytes the worker wrote.
      if (typed.artifactKey) {
        structureUrl = await ctx.presignGet(typed.artifactKey, 15 * 60);
      }
      const target = scoringTarget(job);
      const metaScore = scoreDesignWithLlmPrior({
        metrics: metricsFrom(row),
        ...target,
      });
      return {
        ...typed,
        structureUrl,
        structureExpiresInSec: structureUrl ? 15 * 60 : undefined,
        tool: job?.tool ?? undefined,
        jobId: typed.jobId,
        metaScore,
      };
    }),
});
