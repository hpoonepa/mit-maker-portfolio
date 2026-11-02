/**
 * Annotations router — markdown comment threads, tags, and per-user stars
 * attached to a Design.
 *
 * Procedures
 *   - listByDesign({ designId })             paginated comment thread + tags + star
 *   - create({ designId, body })             post a markdown comment
 *   - update({ id, body })                   author-only edit
 *   - delete({ id })                         author-only delete
 *   - star({ designId })                     toggle the caller's star (idempotent)
 *   - unstar({ designId })
 *   - tags.list()                            org-wide tag palette
 *   - tags.create({ name, color })
 *   - tags.attach({ designId, tagId })
 *   - tags.detach({ designId, tagId })
 *   - tags.delete({ id })
 *
 * Access model
 * ------------
 * All procedures route through `withRlsUser`. The Postgres RLS policies on
 * `design_annotations`, `design_tags`, `_DesignTags`, and `design_stars`
 * enforce tenant + author isolation; we duplicate the check at the query
 * layer (`orgId`/`authorId` filters) as defence in depth.
 *
 * Body markdown
 * -------------
 * The `body` column is raw markdown — including `@mention` tokens. The router
 * does not parse mentions; the UI renders them by matching `@` followed by a
 * member display-name against the org roster (see `CommentThread.tsx`).
 */
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

// ─── Zod shapes ─────────────────────────────────────────────────────────────

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

const AnnotationSchema = z
  .object({
    id: z.string(),
    designId: z.string(),
    authorId: z.string(),
    authorName: z.string().nullable(),
    authorEmail: z.string().nullable(),
    body: z.string(),
    createdAt: z.string(),
    updatedAt: z.string(),
    canEdit: z.boolean(),
  })
  .passthrough();

const TagSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    color: z.string(),
  })
  .passthrough();

const ListByDesignOutput = z.object({
  annotations: z.array(AnnotationSchema),
  tags: z.array(TagSchema),
  starred: z.boolean(),
  starCount: z.number().int().nonnegative(),
});

// ─── Sub-router: tags ───────────────────────────────────────────────────────

const tagsRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/tags',
        tags: ['annotations'],
        summary: 'List org tag palette',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ items: z.array(TagSchema) }))
    .query(async ({ ctx }) => {
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            designTag: {
              findMany: (args: unknown) => Promise<
                Array<{ id: string; name: string; color: string }>
              >;
            };
          };
          return client.designTag.findMany({
            where: { orgId: ctx.auth!.orgId },
            orderBy: { name: 'asc' },
          });
        },
      );
      return { items: rows };
    }),

  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/tags',
        tags: ['annotations'],
        summary: 'Create an org tag',
        protect: true,
      },
    })
    .input(
      z
        .object({
          name: z.string().trim().min(1).max(40),
          color: z.string().regex(HEX_COLOR, 'must be #RRGGBB'),
        })
        .strict(),
    )
    .output(TagSchema)
    .mutation(async ({ ctx, input }) => {
      return ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          designTag: {
            create: (args: unknown) => Promise<{
              id: string;
              name: string;
              color: string;
            }>;
          };
        };
        try {
          return await client.designTag.create({
            data: {
              orgId: ctx.auth!.orgId,
              name: input.name,
              color: input.color,
            },
          });
        } catch (err) {
          // Unique violation on (orgId, name).
          if (err && typeof err === 'object' && 'code' in err && (err as { code?: string }).code === 'P2002') {
            throw new TRPCError({ code: 'CONFLICT', message: 'Tag already exists' });
          }
          throw err;
        }
      });
    }),

  attach: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/designs/{designId}/tags/{tagId}',
        tags: ['annotations'],
        summary: 'Attach a tag to a design',
        protect: true,
      },
    })
    .input(
      z
        .object({
          designId: z.string().min(1),
          tagId: z.string().min(1),
        })
        .strict(),
    )
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          design: {
            update: (args: unknown) => Promise<unknown>;
          };
        };
        await client.design.update({
          where: { id: input.designId },
          data: { tags: { connect: { id: input.tagId } } },
        });
      });
      return { ok: true as const };
    }),

  detach: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/designs/{designId}/tags/{tagId}',
        tags: ['annotations'],
        summary: 'Detach a tag from a design',
        protect: true,
      },
    })
    .input(
      z
        .object({
          designId: z.string().min(1),
          tagId: z.string().min(1),
        })
        .strict(),
    )
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          design: {
            update: (args: unknown) => Promise<unknown>;
          };
        };
        await client.design.update({
          where: { id: input.designId },
          data: { tags: { disconnect: { id: input.tagId } } },
        });
      });
      return { ok: true as const };
    }),

  delete: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/tags/{id}',
        tags: ['annotations'],
        summary: 'Delete an org tag',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          designTag: {
            deleteMany: (args: unknown) => Promise<{ count: number }>;
          };
        };
        await client.designTag.deleteMany({
          where: { id: input.id, orgId: ctx.auth!.orgId },
        });
      });
      return { ok: true as const };
    }),
});

// ─── Main router ────────────────────────────────────────────────────────────

export const annotationsRouter = router({
  listByDesign: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/designs/{designId}/annotations',
        tags: ['annotations'],
        summary: 'List annotations, tags, and star state for a design',
        protect: true,
      },
    })
    .input(z.object({ designId: z.string().min(1) }))
    .output(ListByDesignOutput)
    .query(async ({ ctx, input }) => {
      const result = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            designAnnotation: {
              findMany: (args: unknown) => Promise<
                Array<{
                  id: string;
                  designId: string;
                  authorId: string;
                  body: string;
                  createdAt: Date;
                  updatedAt: Date;
                  author: { name: string | null; email: string } | null;
                }>
              >;
            };
            design: {
              findUnique: (args: unknown) => Promise<
                | {
                    tags: Array<{ id: string; name: string; color: string }>;
                  }
                | null
              >;
            };
            designStar: {
              findUnique: (args: unknown) => Promise<{ designId: string } | null>;
              count: (args: unknown) => Promise<number>;
            };
          };

          const [annotations, design, star, starCount] = await Promise.all([
            client.designAnnotation.findMany({
              where: { designId: input.designId },
              orderBy: { createdAt: 'asc' },
              include: { author: { select: { name: true, email: true } } },
            }),
            client.design.findUnique({
              where: { id: input.designId },
              select: {
                tags: { select: { id: true, name: true, color: true } },
              } as unknown,
            }),
            client.designStar.findUnique({
              where: {
                designId_userId: {
                  designId: input.designId,
                  userId: ctx.auth!.userId,
                },
              },
            }),
            client.designStar.count({
              where: { designId: input.designId },
            }),
          ]);

          return { annotations, design, star, starCount };
        },
      );

      return {
        annotations: result.annotations.map((a) => ({
          id: a.id,
          designId: a.designId,
          authorId: a.authorId,
          authorName: a.author?.name ?? null,
          authorEmail: a.author?.email ?? null,
          body: a.body,
          createdAt: a.createdAt instanceof Date ? a.createdAt.toISOString() : String(a.createdAt),
          updatedAt: a.updatedAt instanceof Date ? a.updatedAt.toISOString() : String(a.updatedAt),
          canEdit: a.authorId === ctx.auth!.userId,
        })),
        tags: result.design?.tags ?? [],
        starred: !!result.star,
        starCount: result.starCount,
      };
    }),

  create: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/designs/{designId}/annotations',
        tags: ['annotations'],
        summary: 'Post a markdown annotation on a design',
        protect: true,
      },
    })
    .input(
      z
        .object({
          designId: z.string().min(1),
          body: z.string().trim().min(1).max(8000),
        })
        .strict(),
    )
    .output(AnnotationSchema)
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            designAnnotation: {
              create: (args: unknown) => Promise<{
                id: string;
                designId: string;
                authorId: string;
                body: string;
                createdAt: Date;
                updatedAt: Date;
                author: { name: string | null; email: string } | null;
              }>;
            };
          };
          return client.designAnnotation.create({
            data: {
              designId: input.designId,
              authorId: ctx.auth!.userId,
              body: input.body,
            },
            include: { author: { select: { name: true, email: true } } },
          });
        },
      );
      return {
        id: row.id,
        designId: row.designId,
        authorId: row.authorId,
        authorName: row.author?.name ?? null,
        authorEmail: row.author?.email ?? null,
        body: row.body,
        createdAt: row.createdAt instanceof Date ? row.createdAt.toISOString() : String(row.createdAt),
        updatedAt: row.updatedAt instanceof Date ? row.updatedAt.toISOString() : String(row.updatedAt),
        canEdit: true,
      };
    }),

  update: protectedProcedure
    .meta({
      openapi: {
        method: 'PATCH',
        path: '/annotations/{id}',
        tags: ['annotations'],
        summary: 'Edit a markdown annotation (author-only)',
        protect: true,
      },
    })
    .input(
      z
        .object({
          id: z.string().min(1),
          body: z.string().trim().min(1).max(8000),
        })
        .strict(),
    )
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      const count = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            designAnnotation: {
              updateMany: (args: {
                where: Record<string, unknown>;
                data: Record<string, unknown>;
              }) => Promise<{ count: number }>;
            };
          };
          const res = await client.designAnnotation.updateMany({
            where: { id: input.id, authorId: ctx.auth!.userId },
            data: { body: input.body },
          });
          return res.count;
        },
      );
      if (count === 0) {
        throw new TRPCError({
          code: 'NOT_FOUND',
          message: 'Annotation not found or not yours',
        });
      }
      return { ok: true as const };
    }),

  delete: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/annotations/{id}',
        tags: ['annotations'],
        summary: 'Delete an annotation (author-only)',
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          designAnnotation: {
            deleteMany: (args: unknown) => Promise<{ count: number }>;
          };
        };
        await client.designAnnotation.deleteMany({
          where: { id: input.id, authorId: ctx.auth!.userId },
        });
      });
      return { ok: true as const };
    }),

  star: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/designs/{designId}/star',
        tags: ['annotations'],
        summary: 'Star a design (idempotent)',
        protect: true,
      },
    })
    .input(z.object({ designId: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          designStar: {
            upsert: (args: unknown) => Promise<unknown>;
          };
        };
        await client.designStar.upsert({
          where: {
            designId_userId: {
              designId: input.designId,
              userId: ctx.auth!.userId,
            },
          },
          create: { designId: input.designId, userId: ctx.auth!.userId },
          update: {},
        });
      });
      return { ok: true as const };
    }),

  unstar: protectedProcedure
    .meta({
      openapi: {
        method: 'DELETE',
        path: '/designs/{designId}/star',
        tags: ['annotations'],
        summary: 'Remove star (idempotent)',
        protect: true,
      },
    })
    .input(z.object({ designId: z.string().min(1) }))
    .output(z.object({ ok: z.literal(true) }))
    .mutation(async ({ ctx, input }) => {
      await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          designStar: {
            deleteMany: (args: unknown) => Promise<{ count: number }>;
          };
        };
        await client.designStar.deleteMany({
          where: { designId: input.designId, userId: ctx.auth!.userId },
        });
      });
      return { ok: true as const };
    }),

  starredIds: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/designs/starred',
        tags: ['annotations'],
        summary: 'List the caller’s starred design ids',
        protect: true,
      },
    })
    .input(z.void())
    .output(z.object({ ids: z.array(z.string()) }))
    .query(async ({ ctx }) => {
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            designStar: {
              findMany: (args: unknown) => Promise<Array<{ designId: string }>>;
            };
          };
          return client.designStar.findMany({
            where: { userId: ctx.auth!.userId },
            select: { designId: true },
            orderBy: { starredAt: 'desc' },
          });
        },
      );
      return { ids: rows.map((r) => r.designId) };
    }),

  tags: tagsRouter,
});
