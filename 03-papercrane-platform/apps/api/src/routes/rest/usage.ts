import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { PrismaClient } from "@papercrane/db";
import { AuthError, requireScope } from "@papercrane/auth";
import { resolveOrgId } from "../../context.js";
import { runWithTenant } from "../../middleware/tenantRLS.js";

/**
 * Usage endpoints — read-only views over `usage_seeds` and the aggregate
 * counters on `organizations`. Write-path (debit/credit) lives in the
 * orchestrator, not here.
 */

export interface UsageDeps {
  prisma: PrismaClient;
}

const HistoryQuerySchema = z
  .object({
    limit: z.coerce.number().int().min(1).max(500).default(100),
    cursor: z.string().datetime().optional(),
  })
  .strict();

export async function registerUsageRoutes(
  app: FastifyInstance,
  deps: UsageDeps,
): Promise<void> {
  app.get("/v1/usage/current", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "usage:read");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const org = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.organization.findUnique({
        where: { id: orgId },
        select: {
          tier: true,
          seedsQuota: true,
          seedsUsed: true,
        },
      });
    });
    if (!org) throw new AuthError("org not found", "org_not_found");

    return {
      tier: org.tier,
      seedsIncluded: org.seedsQuota,
      seedsConsumed: org.seedsUsed,
      seedsRemaining: Math.max(0, org.seedsQuota - org.seedsUsed),
    };
  });

  app.get("/v1/usage/history", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "usage:read");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const { limit, cursor } = HistoryQuerySchema.parse(req.query ?? {});

    const rows = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.usageSeed.findMany({
        where: {
          orgId,
          ...(cursor ? { createdAt: { lt: new Date(cursor) } } : {}),
        },
        orderBy: { createdAt: "desc" },
        take: limit,
        select: {
          id: true,
          jobId: true,
          seeds: true,
          reason: true,
          createdAt: true,
        },
      });
    });

    return {
      entries: rows.map((r) => ({
        id: r.id.toString(),
        jobId: r.jobId,
        seeds: r.seeds,
        reason: r.reason,
        at: r.createdAt.toISOString(),
      })),
      nextCursor:
        rows.length === limit
          ? rows[rows.length - 1]!.createdAt.toISOString()
          : null,
    };
  });
}
