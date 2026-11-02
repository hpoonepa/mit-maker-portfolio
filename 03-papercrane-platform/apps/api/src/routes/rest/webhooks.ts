import { randomBytes } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { PrismaClient } from "@papercrane/db";
import { AuthError, requireScope } from "@papercrane/auth";
import { WebhookEventTypeSchema } from "@papercrane/types";
import { resolveOrgId } from "../../context.js";
import { runWithTenant } from "../../middleware/tenantRLS.js";

/**
 * Webhook subscription CRUD.
 *
 * IMPORTANT: the Prisma `Webhook` model is not yet in the schema; this module
 * uses `prisma.$queryRaw` against the forthcoming `webhooks` table so that
 * the API surface compiles today. When @papercrane/db lands the model, the
 * raw queries flip to typed `prisma.webhook.*` calls with no change to the
 * HTTP surface.
 */

const CreateWebhookSchema = z
  .object({
    url: z.string().url(),
    events: z.array(WebhookEventTypeSchema).min(1),
    /** Optional client-supplied secret; server generates one if absent. */
    secret: z.string().min(16).optional(),
  })
  .strict();

export interface WebhooksDeps {
  prisma: PrismaClient;
}

export async function registerWebhookRoutes(
  app: FastifyInstance,
  deps: WebhooksDeps,
): Promise<void> {
  app.get("/v1/webhooks", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "jobs:read");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");
    const rows = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.$queryRaw<
        Array<{
          id: string;
          url: string;
          events: string[];
          active: boolean;
          created_at: Date;
          last_delivery_at: Date | null;
        }>
      >`SELECT id::text, url, events, active, created_at, last_delivery_at
        FROM webhooks WHERE org_id = ${orgId}::uuid`;
    });
    return { webhooks: rows };
  });

  app.post("/v1/webhooks", async (req, reply) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "jobs:write");
    const body = CreateWebhookSchema.parse(req.body);
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const secret = body.secret ?? generateSecret();
    const created = await runWithTenant(req, deps.prisma, async (tx) => {
      const rows = await tx.$queryRaw<Array<{ id: string }>>`
        INSERT INTO webhooks (org_id, url, events, secret, active)
        VALUES (${orgId}::uuid, ${body.url}, ${body.events}::text[], ${secret}, true)
        RETURNING id::text
      `;
      return rows[0];
    });

    void reply.code(201);
    return { id: created?.id, secret };
  });

  app.delete<{ Params: { id: string } }>(
    "/v1/webhooks/:id",
    async (req, reply) => {
      if (!req.auth) throw new AuthError("auth required", "auth_required");
      requireScope(req.auth, "jobs:write");
      const id = z.string().uuid().parse(req.params.id);
      const orgId = resolveOrgId(req.auth);
      if (!orgId) throw new AuthError("org required", "org_required");
      await runWithTenant(req, deps.prisma, async (tx) => {
        await tx.$executeRaw`DELETE FROM webhooks WHERE id = ${id}::uuid AND org_id = ${orgId}::uuid`;
      });
      void reply.code(204).send();
    },
  );
}

function generateSecret(): string {
  // 32 bytes hex — sufficient entropy, easy for customers to copy.
  return randomBytes(32).toString("hex");
}
