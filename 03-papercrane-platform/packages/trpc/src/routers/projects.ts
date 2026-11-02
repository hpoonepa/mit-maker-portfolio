/**
 * Projects router — CRUD over the user's projects. Projects are tenant-
 * scoped containers (org → projects → targets/jobs). All reads and writes
 * run through `withRlsUser` so Postgres RLS enforces isolation even if
 * our WHERE clauses regress.
 */
import { randomBytes } from 'node:crypto';
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';
import {
  MetaScoreSummarySchema,
  metaScoreSummary,
  scoreDesignWithLlmPrior,
} from '../scoring/llmMetaScorer.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

const ProjectSchema = z
  .object({
    id: z.string(),
    orgId: z.string(),
    name: z.string(),
    slug: z.string(),
    description: z.string().nullable().optional(),
    isPublic: z.boolean().default(false),
    publicId: z.string().nullable().optional(),
    publishedAt: z.date().nullable().optional(),
    createdAt: z.date(),
    updatedAt: z.date(),
  })
  .passthrough();

const PublicMetricPreviewSchema = z.object({
  ipSAE: z.number().nullable(),
  ipTM: z.number().nullable(),
  pDockQ: z.number().nullable(),
  interfaceResidues: z.number().nullable(),
});

const PublicProjectViewSchema = z.object({
  project: z.object({
    name: z.string(),
    description: z.string().nullable(),
    updatedAt: z.string(),
  }),
  org: z.object({ name: z.string() }),
  target: z
    .object({
      name: z.string(),
      pdbId: z.string().nullable(),
    })
    .nullable(),
  summary: z.object({
    completedJobs: z.number().int().nonnegative(),
    designsGenerated: z.number().int().nonnegative(),
  }),
  topCandidates: z.array(
    z.object({
      id: z.string(),
      seed: z.number().int(),
      rank: z.number().int().nullable(),
      tool: z.string(),
      provenance: z.string(),
      length: z.number().int().nonnegative().nullable(),
      metrics: PublicMetricPreviewSchema,
      metaScore: MetaScoreSummarySchema,
    }),
  ),
});

const PublicProjectDbSchema = z.object({
  project: z.object({
    name: z.string(),
    description: z.string().nullable(),
    updatedAt: z.string(),
  }),
  org: z.object({ name: z.string() }),
  target: z
    .object({
      name: z.string(),
      pdbId: z.string().nullable(),
    })
    .nullable(),
  summary: z.object({
    completedJobs: z.coerce.number().int().nonnegative(),
    designsGenerated: z.coerce.number().int().nonnegative(),
  }),
  candidates: z.array(
    z.object({
      id: z.string(),
      seed: z.number().int(),
      rank: z.number().int().nullable(),
      tool: z.string(),
      provenance: z.string(),
      length: z.number().int().nonnegative().nullable(),
      metrics: z.record(z.string(), z.unknown()),
    }),
  ),
});

// Snapshot shape applied to ProjectVersion.snapshot. We keep the JSON open
// (`passthrough`) so future fields land without a schema migration, but pin
// the four load-bearing keys so the diff/revert UIs always know what to read.
const SnapshotSchema = z
  .object({
    name: z.string(),
    description: z.string().nullable(),
    hotspots: z.unknown().nullable(),
    defaultParams: z.record(z.unknown()),
    metadata: z.record(z.unknown()).optional(),
  })
  .passthrough();

const ProjectVersionSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  version: z.number().int().positive(),
  authorId: z.string(),
  description: z.string().nullable(),
  snapshot: SnapshotSchema,
  createdAt: z.date(),
});

export const projectsRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/projects',
        tags: ['projects'],
        summary: 'List projects for the caller’s org',
        protect: true,
      },
    })
    .input(z.object({ limit: z.number().int().positive().max(200).optional() }))
    .output(z.object({ items: z.array(ProjectSchema) }))
    .query(async ({ ctx, input }) => {
      const items = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          project: { findMany: (args: unknown) => Promise<unknown[]> };
        };
        return client.project.findMany({
          where: { orgId: ctx.auth!.orgId },
          orderBy: { createdAt: 'desc' },
          take: input.limit ?? 50,
        });
      });
      return { items: items as z.infer<typeof ProjectSchema>[] };
    }),

  get: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/projects/{id}',
        tags: ['projects'],
        summary: 'Fetch a project by id',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(ProjectSchema)
    .query(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          project: { findFirst: (args: unknown) => Promise<unknown | null> };
        };
        return client.project.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
      });
      if (!row) throw new TRPCError({ code: 'NOT_FOUND', message: 'project not found' });
      return row as z.infer<typeof ProjectSchema>;
    }),

  /**
   * Publish or revoke a read-only project report. The opaque id remains
   * stable across revocation/re-publish cycles, while `isPublic` is always
   * the server-side source of truth for access.
   */
  share: protectedProcedure
    .input(
      z
        .object({
          id: z.string().min(1),
          isPublic: z.boolean(),
        })
        .strict(),
    )
    .output(
      z.object({
        isPublic: z.boolean(),
        publicId: z.string().nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          project: {
            findFirst: (args: unknown) => Promise<{
              publicId: string | null;
              isPublic: boolean;
              publishedAt: Date | null;
            } | null>;
            update: (args: unknown) => Promise<{
              publicId: string | null;
              isPublic: boolean;
            }>;
          };
        };
        const existing = await client.project.findFirst({
          where: { id: input.id, orgId: ctx.auth!.orgId },
          select: { publicId: true, isPublic: true, publishedAt: true },
        });
        if (!existing) return null;

        const publicId =
          existing.publicId ?? `prj_${randomBytes(18).toString('base64url')}`;
        return client.project.update({
          where: { id: input.id, orgId: ctx.auth!.orgId },
          data: {
            isPublic: input.isPublic,
            publicId,
            publishedAt: input.isPublic
              ? existing.publishedAt ?? ctx.now()
              : null,
          },
          select: { publicId: true, isPublic: true },
        });
      });
      if (!row) {
        throw new TRPCError({ code: 'NOT_FOUND', message: 'project not found' });
      }
      return row;
    }),

  /**
   * Anonymous, rate-limited read path backed by a SECURITY DEFINER database
   * function. The function owns the field allowlist and returns null unless
   * the matching project is currently public.
   */
  public: publicProcedure
    .input(
      z
        .object({
          publicId: z.string().regex(/^prj_[A-Za-z0-9_-]{20,64}$/),
        })
        .strict(),
    )
    .output(PublicProjectViewSchema)
    .query(async ({ ctx, input }) => {
      const client = ctx.prisma as unknown as {
        $queryRawUnsafe: <T>(query: string, ...values: unknown[]) => Promise<T>;
      };
      const rows = await client.$queryRawUnsafe<Array<{ data: unknown }>>(
        'SELECT public.get_public_project_share($1) AS data',
        input.publicId,
      );
      const raw = rows[0]?.data;
      if (!raw) {
        throw new TRPCError({ code: 'NOT_FOUND', message: 'public project not found' });
      }
      const parsed = PublicProjectDbSchema.parse(raw);
      const target = parsed.target;
      const topCandidates = parsed.candidates
        .map((candidate) => {
          const detail = scoreDesignWithLlmPrior({
            metrics: candidate.metrics,
            targetName: target?.name ?? null,
            pdbId: target?.pdbId ?? null,
          });
          return {
            ...candidate,
            length: candidate.length && candidate.length > 0 ? candidate.length : null,
            metrics: publicMetricPreview(candidate.metrics),
            metaScore: metaScoreSummary(detail),
          };
        })
        .sort(comparePublicCandidates)
        .slice(0, 5);

      return {
        project: parsed.project,
        org: parsed.org,
        target,
        summary: parsed.summary,
        topCandidates,
      };
    }),

  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/projects',
        tags: ['projects'],
        summary: 'Create a project in the caller’s org',
        protect: true,
      },
    })
    .input(
      z
        .object({
          name: z.string().min(1).max(120),
          slug: z.string().regex(SLUG_RE).max(64),
          description: z.string().max(2000).optional(),
        })
        .strict(),
    )
    .output(ProjectSchema)
    .mutation(async ({ ctx, input }) => {
      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              project: {
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
                findFirst: (args: { where: Record<string, unknown> }) => Promise<unknown>;
              };
            };
            let slug = input.slug;
            let attempt = 0;
            while (attempt < 20) {
              const existing = await client.project.findFirst({
                where: { orgId: ctx.auth!.orgId, slug },
              });
              if (!existing) break;
              attempt += 1;
              slug = `${input.slug}-${attempt + 1}`.slice(0, 64);
            }
            return client.project.create({
              data: {
                orgId: ctx.auth!.orgId,
                name: input.name,
                slug,
                description: input.description ?? null,
              },
            });
          },
        );
        return row as z.infer<typeof ProjectSchema>;
      } catch (err) {
        // Race: another request claimed the slug between findFirst+create.
        const code = (err as { code?: string })?.code;
        if (code === 'P2002') {
          throw new TRPCError({
            code: 'CONFLICT',
            message: 'a project with this slug already exists',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to create project',
        });
      }
    }),

  update: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/projects/{id}',
        tags: ['projects'],
        summary: 'Update a project',
        protect: true,
      },
    })
    .input(
      z
        .object({
          id: z.string().min(1),
          name: z.string().min(1).max(120).optional(),
          description: z.string().max(2000).optional(),
        })
        .strict(),
    )
    .output(ProjectSchema)
    .mutation(async ({ ctx, input }) => {
      const { id, ...data } = input;
      try {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              project: {
                update: (args: {
                  where: Record<string, unknown>;
                  data: Record<string, unknown>;
                }) => Promise<unknown>;
              };
            };
            return client.project.update({
              where: { id, orgId: ctx.auth!.orgId },
              data,
            });
          },
        );
        return row as z.infer<typeof ProjectSchema>;
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2025') {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'project not found',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to update project',
        });
      }
    }),

  delete: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/projects/{id}',
        tags: ['projects'],
        summary: 'Delete a project (soft-delete if supported)',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      try {
        await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
          const client = tx as unknown as {
            project: {
              delete: (args: { where: Record<string, unknown> }) => Promise<unknown>;
            };
          };
          return client.project.delete({
            where: { id: input.id, orgId: ctx.auth!.orgId },
          });
        });
        return { ok: true as const };
      } catch (err) {
        const code = (err as { code?: string })?.code;
        if (code === 'P2025') {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'project not found',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to delete project',
        });
      }
    }),

  // ── Versioning (Wave 14) ────────────────────────────────────────────────
  // Versions are append-only snapshots of a project's load-bearing state
  // (name, description, hotspots, default params). They power the project
  // history sidebar, diff UI, and revert. Forking is sibling to versioning:
  // it spawns a *new* project that links back to the source via metadata,
  // and does not touch the source's version history.

  versions: router({
    list: protectedProcedure
      .input(
        z.object({
          projectId: z.string().min(1),
          limit: z.number().int().positive().max(200).optional(),
        }),
      )
      .output(z.object({ items: z.array(ProjectVersionSchema) }))
      .query(async ({ ctx, input }) => {
        const items = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              project: { findFirst: (args: unknown) => Promise<unknown | null> };
              projectVersion: {
                findMany: (args: unknown) => Promise<unknown[]>;
              };
            };
            // Authorize: ensure caller can see the project (RLS will also
            // enforce this on the version select, but a fast 404 beats a
            // silent empty list).
            const project = await client.project.findFirst({
              where: { id: input.projectId, orgId: ctx.auth!.orgId },
            });
            if (!project) return null;
            return client.projectVersion.findMany({
              where: { projectId: input.projectId },
              orderBy: [{ version: 'desc' }],
              take: input.limit ?? 50,
            });
          },
        );
        if (items === null) {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'project not found' });
        }
        return { items: items as z.infer<typeof ProjectVersionSchema>[] };
      }),

    get: protectedProcedure
      .input(
        z.object({
          projectId: z.string().min(1),
          version: z.number().int().positive(),
        }),
      )
      .output(ProjectVersionSchema)
      .query(async ({ ctx, input }) => {
        const row = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              project: { findFirst: (args: unknown) => Promise<unknown | null> };
              projectVersion: {
                findUnique: (args: unknown) => Promise<unknown | null>;
              };
            };
            const project = await client.project.findFirst({
              where: { id: input.projectId, orgId: ctx.auth!.orgId },
            });
            if (!project) return null;
            return client.projectVersion.findUnique({
              where: {
                projectId_version: {
                  projectId: input.projectId,
                  version: input.version,
                },
              },
            });
          },
        );
        if (!row) {
          throw new TRPCError({ code: 'NOT_FOUND', message: 'version not found' });
        }
        return row as z.infer<typeof ProjectVersionSchema>;
      }),

    save: protectedProcedure
      .input(
        z
          .object({
            projectId: z.string().min(1),
            description: z.string().max(500).optional(),
            snapshot: SnapshotSchema,
          })
          .strict(),
      )
      .output(ProjectVersionSchema)
      .mutation(async ({ ctx, input }) => {
        const row = await createNextVersion(ctx, {
          projectId: input.projectId,
          authorId: ctx.auth.userId,
          description: input.description ?? null,
          snapshot: input.snapshot,
        });
        return row;
      }),
  }),

  revert: protectedProcedure
    .input(
      z
        .object({
          projectId: z.string().min(1),
          version: z.number().int().positive(),
        })
        .strict(),
    )
    .output(ProjectVersionSchema)
    .mutation(async ({ ctx, input }) => {
      // Revert = read the target snapshot, then APPEND a new version that
      // copies it. We deliberately do not mutate-in-place — that would
      // collapse history and break the audit trail. Updating the live
      // project row to match is the caller's responsibility (the UI calls
      // `projects.update` + the relevant target/hotspot mutation after a
      // successful revert), keeping this endpoint snapshot-only.
      const target = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            project: { findFirst: (args: unknown) => Promise<unknown | null> };
            projectVersion: {
              findUnique: (args: unknown) => Promise<unknown | null>;
            };
          };
          const project = await client.project.findFirst({
            where: { id: input.projectId, orgId: ctx.auth!.orgId },
          });
          if (!project) return null;
          return client.projectVersion.findUnique({
            where: {
              projectId_version: {
                projectId: input.projectId,
                version: input.version,
              },
            },
          });
        },
      );
      if (!target) {
        throw new TRPCError({ code: 'NOT_FOUND', message: 'version not found' });
      }
      const targetTyped = target as { snapshot: unknown };
      return createNextVersion(ctx, {
        projectId: input.projectId,
        authorId: ctx.auth.userId,
        description: `Reverted to v${input.version}`,
        snapshot: targetTyped.snapshot as z.infer<typeof SnapshotSchema>,
      });
    }),

  fork: protectedProcedure
    .input(
      z
        .object({
          projectId: z.string().min(1),
          // Fork from a specific version (defaults to "current state").
          fromVersion: z.number().int().positive().optional(),
          name: z.string().min(1).max(120).optional(),
        })
        .strict(),
    )
    .output(ProjectSchema)
    .mutation(async ({ ctx, input }) => {
      try {
        const created = await ctx.withRlsUser(
          ctx.prisma,
          ctx.auth.userId,
          async (tx) => {
            const client = tx as unknown as {
              project: {
                findFirst: (args: unknown) => Promise<unknown | null>;
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
              };
              target: {
                findMany: (args: unknown) => Promise<unknown[]>;
                create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
              };
              projectVersion: {
                findUnique: (args: unknown) => Promise<unknown | null>;
              };
            };
            // 1. Source project must be visible to the caller.
            const source = (await client.project.findFirst({
              where: { id: input.projectId, orgId: ctx.auth!.orgId },
            })) as
              | {
                  id: string;
                  name: string;
                  slug: string;
                  description: string | null;
                }
              | null;
            if (!source) {
              throw new TRPCError({
                code: 'NOT_FOUND',
                message: 'project not found',
              });
            }

            // 2. Resolve which snapshot we're forking from. If a `fromVersion`
            //    was supplied, pin to that snapshot; otherwise use the live
            //    target rows.
            let pinnedSnapshot:
              | z.infer<typeof SnapshotSchema>
              | null = null;
            if (input.fromVersion) {
              const v = (await client.projectVersion.findUnique({
                where: {
                  projectId_version: {
                    projectId: input.projectId,
                    version: input.fromVersion,
                  },
                },
              })) as { snapshot: unknown } | null;
              if (!v) {
                throw new TRPCError({
                  code: 'NOT_FOUND',
                  message: 'version not found',
                });
              }
              pinnedSnapshot = v.snapshot as z.infer<typeof SnapshotSchema>;
            }

            const baseName = input.name ?? `${source.name} (fork)`;
            const baseSlug = source.slug
              ? `${source.slug}-fork`.slice(0, 64)
              : 'fork';

            // 3. Pick a non-conflicting slug.
            let slug = baseSlug;
            let attempt = 0;
            while (attempt < 20) {
              const existing = await client.project.findFirst({
                where: { orgId: ctx.auth!.orgId, slug },
              });
              if (!existing) break;
              attempt += 1;
              slug = `${baseSlug}-${attempt + 1}`.slice(0, 64);
            }

            // 4. Materialize the new project. We don't carry over the
            //    source's version history — the fork starts at v1 with its
            //    own snapshot — but we do tag it via metadata-style fields
            //    on the seed version so the UI can show "Forked from X".
            const project = (await client.project.create({
              data: {
                orgId: ctx.auth!.orgId,
                name: baseName,
                slug,
                description: pinnedSnapshot?.description ?? source.description,
                createdBy: ctx.auth!.userId,
              },
            })) as { id: string };

            // 5. Copy the source's targets (name + hotspots + pdb).
            //    Hotspots travel with the target rather than the project.
            const sourceTargets = (await client.target.findMany({
              where: { projectId: input.projectId, orgId: ctx.auth!.orgId },
            })) as Array<{
              name: string;
              pdbId: string | null;
              artifactKey: string;
              hotspots: unknown;
              checksum: string;
            }>;
            for (const t of sourceTargets) {
              await client.target.create({
                data: {
                  orgId: ctx.auth!.orgId,
                  projectId: project.id,
                  name: t.name,
                  pdbId: t.pdbId,
                  artifactKey: t.artifactKey,
                  hotspots: t.hotspots ?? null,
                  checksum: t.checksum,
                },
              });
            }

            // 6. Seed the fork with v1 — a snapshot whose metadata records
            //    the source. The diff UI on the new project shows nothing
            //    "before" v1, which is correct for a freshly-forked project.
            const seedSnapshot: z.infer<typeof SnapshotSchema> = {
              name: baseName,
              description: pinnedSnapshot?.description ?? source.description,
              hotspots: pinnedSnapshot?.hotspots ?? null,
              defaultParams: pinnedSnapshot?.defaultParams ?? {},
              metadata: {
                forkedFrom: {
                  projectId: source.id,
                  projectName: source.name,
                  fromVersion: input.fromVersion ?? null,
                },
              },
            };
            await createNextVersionInTx(tx, {
              projectId: project.id,
              authorId: ctx.auth!.userId,
              description: `Forked from ${source.name}`,
              snapshot: seedSnapshot,
            });

            return project;
          },
        );
        return created as z.infer<typeof ProjectSchema>;
      } catch (err) {
        if (err instanceof TRPCError) throw err;
        const code = (err as { code?: string })?.code;
        if (code === 'P2002') {
          throw new TRPCError({
            code: 'CONFLICT',
            message: 'a project with this slug already exists',
          });
        }
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'failed to fork project',
        });
      }
    }),
});

function publicMetricPreview(metrics: Record<string, unknown>): z.infer<typeof PublicMetricPreviewSchema> {
  return {
    ipSAE: finiteMetric(metrics.computational__boltz2_min_ipsae),
    ipTM: finiteMetric(metrics.computational__boltz2_iptm),
    pDockQ: finiteMetric(metrics.pdockq),
    interfaceResidues: finiteMetric(metrics.computational__interface_residues),
  };
}

function finiteMetric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function comparePublicCandidates(
  left: z.infer<typeof PublicProjectViewSchema>['topCandidates'][number],
  right: z.infer<typeof PublicProjectViewSchema>['topCandidates'][number],
): number {
  const scoreDelta = (right.metaScore.score ?? -1) - (left.metaScore.score ?? -1);
  if (scoreDelta !== 0) return scoreDelta;
  const coverageDelta = right.metaScore.coverage - left.metaScore.coverage;
  if (coverageDelta !== 0) return coverageDelta;
  return (left.rank ?? Number.MAX_SAFE_INTEGER) - (right.rank ?? Number.MAX_SAFE_INTEGER);
}

// ── Internal helpers ───────────────────────────────────────────────────────

interface CreateNextVersionInput {
  projectId: string;
  authorId: string;
  description: string | null;
  snapshot: z.infer<typeof SnapshotSchema>;
}

/**
 * Create the next version row for a project. Wraps `createNextVersionInTx`
 * in an RLS-scoped transaction. Returns the created row.
 *
 * Race handling: two concurrent writers can read the same `MAX(version)`
 * and both try to insert the same `(projectId, version)` pair. The unique
 * constraint catches this; the loser retries up to 3 times. We deliberately
 * keep the retry count tiny — if you can't get past 3, your project has
 * pathological write contention and we'd rather surface the error.
 */
async function createNextVersion(
  ctx: { prisma: unknown; withRlsUser: <T>(p: any, uid: string, fn: (tx: any) => Promise<T>) => Promise<T>; auth: { userId: string; orgId: string } },
  input: CreateNextVersionInput,
): Promise<z.infer<typeof ProjectVersionSchema>> {
  let lastErr: unknown = null;
  for (let i = 0; i < 3; i += 1) {
    try {
      return await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        // Authorize parent project visibility.
        const client = tx as unknown as {
          project: { findFirst: (args: unknown) => Promise<unknown | null> };
        };
        const project = await client.project.findFirst({
          where: { id: input.projectId, orgId: ctx.auth.orgId },
        });
        if (!project) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'project not found',
          });
        }
        return createNextVersionInTx(tx, input);
      });
    } catch (err) {
      lastErr = err;
      const code = (err as { code?: string })?.code;
      if (code !== 'P2002') break;
    }
  }
  if (lastErr instanceof TRPCError) throw lastErr;
  throw new TRPCError({
    code: 'INTERNAL_SERVER_ERROR',
    message: 'failed to save version',
  });
}

/**
 * Insert the next-numbered version row inside an existing transaction.
 * Used by both `versions.save` and `fork` (so the seed v1 of a fork is
 * created in the same atomic step as the new project + targets).
 */
async function createNextVersionInTx(
  tx: unknown,
  input: CreateNextVersionInput,
): Promise<z.infer<typeof ProjectVersionSchema>> {
  const client = tx as unknown as {
    projectVersion: {
      aggregate: (args: unknown) => Promise<{ _max: { version: number | null } }>;
      create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
    };
  };
  const agg = await client.projectVersion.aggregate({
    where: { projectId: input.projectId },
    _max: { version: true },
  });
  const next = (agg._max.version ?? 0) + 1;
  const row = await client.projectVersion.create({
    data: {
      projectId: input.projectId,
      version: next,
      authorId: input.authorId,
      description: input.description,
      snapshot: input.snapshot as unknown as Record<string, unknown>,
    },
  });
  return row as z.infer<typeof ProjectVersionSchema>;
}
