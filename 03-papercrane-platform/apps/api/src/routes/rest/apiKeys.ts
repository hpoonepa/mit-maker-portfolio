import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { PrismaClient } from "@papercrane/db";
import {
  AuthError,
  generateApiKey,
  requireScope,
  type ApiKeyEnv,
} from "@papercrane/auth";
import { ApiKeyScopeSchema } from "@papercrane/types";
import { resolveOrgId } from "../../context.js";
import { runWithTenant } from "../../middleware/tenantRLS.js";

/**
 * API key CRUD.
 *
 * - GET  /v1/keys            — list active keys (never returns the secret)
 * - POST /v1/keys            — create a new key, returns plaintext ONCE
 * - DELETE /v1/keys/:id      — revoke (soft-delete via revokedAt)
 *
 * All writes require the `keys:manage` scope, which Frontier owner keys and
 * user sessions have; regular Pro keys typically do not.
 */

const CreateKeySchema = z
  .object({
    name: z.string().min(1).max(100),
    scopes: z.array(ApiKeyScopeSchema).min(1),
    env: z.enum(["live", "test"]).default("live"),
  })
  .strict();

export interface ApiKeyDeps {
  prisma: PrismaClient;
}

export async function registerApiKeyRoutes(
  app: FastifyInstance,
  deps: ApiKeyDeps,
): Promise<void> {
  app.get("/v1/keys", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "keys:manage");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const keys = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.apiKey.findMany({
        where: { orgId, revokedAt: null },
        orderBy: { createdAt: "desc" },
        select: {
          id: true,
          name: true,
          prefix: true,
          scopes: true,
          lastUsedAt: true,
          createdAt: true,
        },
      });
    });

    return { keys };
  });

  app.post("/v1/keys", async (req, reply) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "keys:manage");
    const body = CreateKeySchema.parse(req.body);
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const { fullKey, prefix, hash } = await generateApiKey(
      body.env as ApiKeyEnv,
    );

    const created = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.apiKey.create({
        data: {
          orgId,
          name: body.name,
          prefix,
          hash,
          scopes: body.scopes,
        },
        select: {
          id: true,
          name: true,
          prefix: true,
          scopes: true,
          createdAt: true,
        },
      });
    });

    void reply.code(201);
    // IMPORTANT: `fullKey` is returned exactly once. The server never retains it.
    return { ...created, key: fullKey };
  });

  app.delete<{ Params: { id: string } }>("/v1/keys/:id", async (req, reply) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    requireScope(req.auth, "keys:manage");
    const id = z.string().uuid().parse(req.params.id);
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    await runWithTenant(req, deps.prisma, async (tx) => {
      await tx.apiKey.updateMany({
        where: { id, orgId, revokedAt: null },
        data: { revokedAt: new Date() },
      });
    });

    void reply.code(204).send();
  });
}
