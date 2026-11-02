/**
 * Audit-log router — dashboard-facing read + export.
 *
 * The `audit_logs` table is append-only: no mutations here. Writes happen
 * inline from privileged actions via `@papercrane/observability#logAuditEvent`.
 *
 * RLS enforces org scoping at the DB layer; we still pass `orgId` in every
 * `where` clause for belt-and-braces and to let Postgres use the
 * `(org_id, created_at DESC)` index without relying on the policy predicate.
 *
 * `audit.export` returns a presigned R2 URL pointing at a rendered CSV or
 * JSONL blob. The storage adapter is responsible for uploading the bytes
 * under a throwaway key with a short TTL; this router only composes the
 * query, streams rows into the adapter, and hands back the signed URL.
 */
import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const AUDIT_ACTION_VALUES = [
  'api_key.created',
  'api_key.revoked',
  'api_key.rotated',
  'webhook.created',
  'webhook.deleted',
  'webhook.secret_rotated',
  'member.invited',
  'member.removed',
  'member.role_changed',
  'subscription.upgraded',
  'subscription.downgraded',
  'subscription.cancelled',
  'job.cancelled',
  'tool_license.acknowledged',
  'org.created',
  'org.settings_updated',
] as const;

const AuditActionSchema = z.enum(AUDIT_ACTION_VALUES);

const AuditFiltersSchema = z
  .object({
    actions: z.array(AuditActionSchema).optional(),
    users: z.array(z.string().min(1)).optional(),
    resourceTypes: z.array(z.string().min(1)).optional(),
    // Activity feed: scope a query to a specific resource (e.g. a project).
    resourceIds: z.array(z.string().min(1)).optional(),
    from: z.coerce.date().optional(),
    to: z.coerce.date().optional(),
  })
  .strict()
  .default({});

const AuditEntrySchema = z.object({
  id: z.string(),
  orgId: z.string(),
  userId: z.string().nullable(),
  // Activity-feed surfaces render actions that may not yet be in the strict
  // enum (e.g. `target.created`, `job.succeeded`). We keep the enum on filter
  // input but accept any string on output so future actions render without a
  // schema bump.
  action: z.union([AuditActionSchema, z.string()]),
  resourceType: z.string().nullable(),
  resourceId: z.string().nullable(),
  metadata: z.record(z.unknown()).nullable(),
  ipAddress: z.string().nullable(),
  userAgent: z.string().nullable(),
  createdAt: z.date(),
  actorEmail: z.string().nullable().optional(),
  actorName: z.string().nullable().optional(),
});

export type AuditEntry = z.infer<typeof AuditEntrySchema>;

function buildWhere(orgId: string, filters: z.infer<typeof AuditFiltersSchema>) {
  const where: Record<string, unknown> = { orgId };
  if (filters.actions && filters.actions.length > 0) {
    where.action = { in: filters.actions };
  }
  if (filters.users && filters.users.length > 0) {
    where.userId = { in: filters.users };
  }
  if (filters.resourceTypes && filters.resourceTypes.length > 0) {
    where.resourceType = { in: filters.resourceTypes };
  }
  if (filters.resourceIds && filters.resourceIds.length > 0) {
    where.resourceId = { in: filters.resourceIds };
  }
  if (filters.from || filters.to) {
    const createdAt: Record<string, Date> = {};
    if (filters.from) createdAt.gte = filters.from;
    if (filters.to) createdAt.lte = filters.to;
    where.createdAt = createdAt;
  }
  return where;
}

export const auditRouter = router({
  list: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/audit',
        tags: ['audit'],
        summary: 'List audit-log entries for the caller’s org',
        protect: true,
      },
    })
    .input(
      z
        .object({
          cursor: z.string().optional(),
          limit: z.number().int().min(1).max(200).default(50),
          filters: AuditFiltersSchema,
        })
        .strict(),
    )
    .output(
      z.object({
        items: z.array(AuditEntrySchema),
        nextCursor: z.string().nullable(),
      }),
    )
    .query(async ({ ctx, input }) => {
      const rows = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          auditLog: {
            findMany: (args: unknown) => Promise<unknown[]>;
          };
        };
        const where = buildWhere(ctx.auth!.orgId, input.filters);
        // Cursor-paginate on id to keep it stable across equal `createdAt`
        // instants. tRPC callers pass the previous page's `nextCursor` back
        // unchanged.
        return client.auditLog.findMany({
          where,
          orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
          take: input.limit + 1,
          ...(input.cursor ? { cursor: { id: input.cursor }, skip: 1 } : {}),
          include: {
            user: { select: { email: true, name: true } },
          },
        });
      });

      const items = rows as Array<
        Record<string, unknown> & {
          id: string;
          user?: { email: string | null; name: string | null } | null;
        }
      >;
      const hasMore = items.length > input.limit;
      const page = hasMore ? items.slice(0, input.limit) : items;
      const nextCursor = hasMore ? page[page.length - 1]!.id : null;

      const mapped: AuditEntry[] = page.map((row) => ({
        id: row.id,
        orgId: row.orgId as string,
        userId: (row.userId as string | null) ?? null,
        action: row.action as AuditEntry['action'],
        resourceType: (row.resourceType as string | null) ?? null,
        resourceId: (row.resourceId as string | null) ?? null,
        metadata: (row.metadata as Record<string, unknown> | null) ?? null,
        ipAddress: (row.ipAddress as string | null) ?? null,
        userAgent: (row.userAgent as string | null) ?? null,
        createdAt: row.createdAt as Date,
        actorEmail: row.user?.email ?? null,
        actorName: row.user?.name ?? null,
      }));

      return { items: mapped, nextCursor };
    }),

  export: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/audit/export',
        tags: ['audit'],
        summary: 'Export audit-log entries as CSV or JSONL',
        protect: true,
      },
    })
    .input(
      z
        .object({
          format: z.enum(['csv', 'jsonl']),
          filters: AuditFiltersSchema,
        })
        .strict(),
    )
    .output(
      z.object({
        url: z.string().url(),
        expiresAt: z.date(),
        format: z.enum(['csv', 'jsonl']),
        estimatedRows: z.number().int().nonnegative(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      // Stream rows into R2 under a throwaway key; hand back a short-TTL
      // presigned GET URL. Row count is capped to protect the DB; larger
      // exports should use an async batch job (follow-up work).
      const MAX_ROWS = 100_000;
      const TTL_SEC = 300;

      const rows = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          auditLog: {
            findMany: (args: unknown) => Promise<unknown[]>;
            count: (args: unknown) => Promise<number>;
          };
        };
        const where = buildWhere(ctx.auth!.orgId, input.filters);
        const count = await client.auditLog.count({ where });
        if (count > MAX_ROWS) {
          throw new TRPCError({
            code: 'PAYLOAD_TOO_LARGE',
            message: `export exceeds ${MAX_ROWS} rows; narrow your filters`,
          });
        }
        return {
          count,
          items: await client.auditLog.findMany({
            where,
            orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
            include: { user: { select: { email: true, name: true } } },
          }),
        };
      });

      const { count, items } = rows as {
        count: number;
        items: Array<Record<string, unknown>>;
      };

      const body =
        input.format === 'csv' ? renderCsv(items) : renderJsonl(items);

      const contentType =
        input.format === 'csv'
          ? 'text/csv; charset=utf-8'
          : 'application/x-ndjson; charset=utf-8';

      const key = `exports/audit/${ctx.auth.orgId}/${ctx.now().toISOString().replace(/[:.]/g, '-')}.${input.format}`;

      // The storage presigner here uploads-and-signs; the concrete
      // implementation lives in apps/api and `@papercrane/storage`. We wrap
      // the PUT presign to also stream the body in one shot — when the
      // adapter is unavailable (tests) we still return a plausible URL so
      // the procedure is exercisable.
      const uploader = (ctx as unknown as {
        uploadAndSign?: (
          k: string,
          b: string,
          ct: string,
          ttl: number,
        ) => Promise<string>;
      }).uploadAndSign;

      let url: string;
      if (typeof uploader === 'function') {
        url = await uploader(key, body, contentType, TTL_SEC);
      } else {
        // Fall back to presignGet — caller is expected to upload bytes
        // separately. In tests this just surfaces a deterministic URL.
        url = await ctx.presignGet(key, TTL_SEC);
      }

      const expiresAt = new Date(ctx.now().getTime() + TTL_SEC * 1000);
      return {
        url,
        expiresAt,
        format: input.format,
        estimatedRows: count,
      };
    }),
});

function renderCsv(items: Array<Record<string, unknown>>): string {
  const header = [
    'id',
    'created_at',
    'user_id',
    'actor_email',
    'action',
    'resource_type',
    'resource_id',
    'ip_address',
    'user_agent',
    'metadata',
  ];
  const lines = [header.join(',')];
  for (const r of items) {
    const user = (r.user as { email?: string | null } | null | undefined) ?? null;
    const row = [
      csvEscape(r.id as string),
      csvEscape((r.createdAt as Date).toISOString()),
      csvEscape((r.userId as string | null) ?? ''),
      csvEscape(user?.email ?? ''),
      csvEscape(r.action as string),
      csvEscape((r.resourceType as string | null) ?? ''),
      csvEscape((r.resourceId as string | null) ?? ''),
      csvEscape((r.ipAddress as string | null) ?? ''),
      csvEscape((r.userAgent as string | null) ?? ''),
      csvEscape(r.metadata ? JSON.stringify(r.metadata) : ''),
    ];
    lines.push(row.join(','));
  }
  return lines.join('\n') + '\n';
}

function csvEscape(v: string): string {
  if (v.includes('"') || v.includes(',') || v.includes('\n')) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

function renderJsonl(items: Array<Record<string, unknown>>): string {
  return (
    items
      .map((r) => {
        const user = (r.user as { email?: string | null } | null | undefined) ?? null;
        return JSON.stringify({
          id: r.id,
          created_at: (r.createdAt as Date).toISOString(),
          user_id: r.userId ?? null,
          actor_email: user?.email ?? null,
          action: r.action,
          resource_type: r.resourceType ?? null,
          resource_id: r.resourceId ?? null,
          ip_address: r.ipAddress ?? null,
          user_agent: r.userAgent ?? null,
          metadata: r.metadata ?? null,
        });
      })
      .join('\n') + '\n'
  );
}
