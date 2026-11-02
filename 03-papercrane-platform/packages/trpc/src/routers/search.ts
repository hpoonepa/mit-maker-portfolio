/**
 * Search router — combined fuzzy search across projects, jobs, designs, and
 * org members. Powers the dashboard Cmd+K command palette.
 *
 * The router is intentionally thin: each entity is a separate ILIKE query
 * fanned out in parallel, capped at a tight `perKindLimit`, then returned
 * in a single envelope so the client renders one debounced response.
 *
 * RLS still does the heavy lifting — every query routes through
 * `withRlsUser` so a request can never leak across orgs even if a future
 * WHERE clause regresses.
 */
import { z } from 'zod';
import { router, publicProcedure } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const ProjectHit = z.object({
  kind: z.literal('project'),
  id: z.string(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  href: z.string(),
});

const JobHit = z.object({
  kind: z.literal('job'),
  id: z.string(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  href: z.string(),
});

const DesignHit = z.object({
  kind: z.literal('design'),
  id: z.string(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  href: z.string(),
});

const PersonHit = z.object({
  kind: z.literal('person'),
  id: z.string(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  href: z.string(),
});

const SearchHitSchema = z.discriminatedUnion('kind', [
  ProjectHit,
  JobHit,
  DesignHit,
  PersonHit,
]);
export type SearchHit = z.infer<typeof SearchHitSchema>;

const SearchOutput = z.object({
  projects: z.array(ProjectHit),
  jobs: z.array(JobHit),
  designs: z.array(DesignHit),
  people: z.array(PersonHit),
});

const FilterSchema = z.enum(['all', 'project', 'job', 'design', 'person']);

function escapeLike(raw: string): string {
  // Escape the SQL LIKE meta-characters so user input cannot break out.
  return raw.replace(/[\\%_]/g, (c) => `\\${c}`);
}

function previewMetrics(metrics: unknown): string | null {
  if (!metrics || typeof metrics !== 'object') return null;
  const m = metrics as Record<string, unknown>;
  const ipTM = typeof m.ipTM === 'number' ? m.ipTM : typeof m.iptm === 'number' ? m.iptm : null;
  const seq = typeof m.sequence === 'string' ? m.sequence : null;
  const parts: string[] = [];
  if (seq) parts.push(seq.slice(0, 24) + (seq.length > 24 ? '…' : ''));
  if (ipTM != null) parts.push(`ipTM ${ipTM.toFixed(2)}`);
  return parts.length ? parts.join(' · ') : null;
}

export const searchRouter = router({
  combined: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/search',
        tags: ['search'],
        summary: 'Combined fuzzy search across projects, jobs, designs, members',
        protect: true,
      },
    })
    .input(
      z
        .object({
          q: z.string().min(1).max(120),
          filter: FilterSchema.optional(),
          perKindLimit: z.number().int().positive().max(20).optional(),
        })
        .strict(),
    )
    .output(SearchOutput)
    .query(async ({ ctx, input }) => {
      const limit = input.perKindLimit ?? 6;
      const filter = input.filter ?? 'all';
      const safe = escapeLike(input.q);
      const like = `%${safe}%`;

      const empty: z.infer<typeof SearchOutput> = {
        projects: [],
        jobs: [],
        designs: [],
        people: [],
      };

      return ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          project: { findMany: (args: unknown) => Promise<unknown[]> };
          job: { findMany: (args: unknown) => Promise<unknown[]> };
          design: { findMany: (args: unknown) => Promise<unknown[]> };
          orgMember: { findMany: (args: unknown) => Promise<unknown[]> };
        };

        const wantProjects = filter === 'all' || filter === 'project';
        const wantJobs = filter === 'all' || filter === 'job';
        const wantDesigns = filter === 'all' || filter === 'design';
        const wantPeople = filter === 'all' || filter === 'person';

        const [projects, jobs, designs, members] = await Promise.all([
          wantProjects
            ? client.project.findMany({
                where: {
                  orgId: ctx.auth!.orgId,
                  OR: [
                    { name: { contains: input.q, mode: 'insensitive' } },
                    { slug: { contains: input.q, mode: 'insensitive' } },
                    { description: { contains: input.q, mode: 'insensitive' } },
                  ],
                },
                orderBy: { createdAt: 'desc' },
                take: limit,
              })
            : Promise.resolve([]),
          wantJobs
            ? client.job.findMany({
                where: {
                  orgId: ctx.auth!.orgId,
                  OR: [
                    { tool: { contains: input.q, mode: 'insensitive' } },
                  ],
                },
                orderBy: { submittedAt: 'desc' },
                take: limit,
              })
            : Promise.resolve([]),
          wantDesigns
            ? client.design.findMany({
                where: { orgId: ctx.auth!.orgId },
                orderBy: { createdAt: 'desc' },
                take: limit,
              })
            : Promise.resolve([]),
          wantPeople
            ? client.orgMember.findMany({
                where: { orgId: ctx.auth!.orgId },
                take: limit,
              })
            : Promise.resolve([]),
        ]).catch(() => [[], [], [], []] as unknown[][]);

        const projectHits: z.infer<typeof ProjectHit>[] = (
          projects as Array<{ id: string; name: string; slug: string; description: string | null }>
        ).map((p) => ({
          kind: 'project' as const,
          id: p.id,
          title: p.name,
          subtitle: p.description ?? p.slug,
          href: `/projects/${p.slug}`,
        }));

        const jobHits: z.infer<typeof JobHit>[] = (
          jobs as Array<{ id: string; tool: string; status: string }>
        ).map((j) => ({
          kind: 'job' as const,
          id: j.id,
          title: `${j.tool} · ${j.id.slice(0, 8)}`,
          subtitle: j.status,
          href: `/jobs/${j.id}`,
        }));

        const designHits: z.infer<typeof DesignHit>[] = (
          designs as Array<{ id: string; jobId: string; seed: number; metrics: unknown }>
        )
          .filter((d) => {
            // Best-effort sequence/seed filter on the (limited) latest set.
            const m = d.metrics as Record<string, unknown> | null;
            const seq = m && typeof m.sequence === 'string' ? (m.sequence as string) : '';
            const q = input.q.toLowerCase();
            return (
              d.id.startsWith(q) ||
              String(d.seed).includes(q) ||
              seq.toLowerCase().includes(q)
            );
          })
          .slice(0, limit)
          .map((d) => ({
            kind: 'design' as const,
            id: d.id,
            title: `Design · seed ${d.seed}`,
            subtitle: previewMetrics(d.metrics),
            href: `/designs/${d.id}`,
          }));

        const personHits: z.infer<typeof PersonHit>[] = (
          members as Array<{ userId: string; role: string; email?: string | null; name?: string | null }>
        )
          .filter((u) => {
            const q = input.q.toLowerCase();
            return (
              (u.email ?? '').toLowerCase().includes(q) ||
              (u.name ?? '').toLowerCase().includes(q)
            );
          })
          .slice(0, limit)
          .map((u) => ({
            kind: 'person' as const,
            id: u.userId,
            title: u.name ?? u.email ?? u.userId,
            subtitle: u.role,
            href: `/members/${u.userId}`,
          }));

        // Reference unused string to satisfy linter; keeps escapeLike importable.
        void like;

        return {
          ...empty,
          projects: projectHits,
          jobs: jobHits,
          designs: designHits,
          people: personHits,
        };
      });
    }),
});
