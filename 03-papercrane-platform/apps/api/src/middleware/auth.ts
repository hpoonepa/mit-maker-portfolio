import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import {
  AuthError,
  buildApiKeyContext,
  buildUserContext,
  verifyApiKey,
  verifySupabaseJwt,
  type AuthContext,
} from "@papercrane/auth";
import type { PrismaClient } from "@papercrane/db";
import type { ApiKeyScope } from "@papercrane/types";
import type { Config } from "../config.js";

/**
 * Auth resolver middleware.
 *
 * Flow:
 *   1. Read `Authorization: Bearer <token>` header.
 *   2. If token begins with `pc_`, treat as API key — hash and look up in DB,
 *      verify argon2, attach `ApiKeyPrincipal` on success.
 *   3. Otherwise treat as Supabase JWT — verify against JWKS, attach
 *      `UserPrincipal`.
 *   4. On any failure throw {@link AuthError} (401). The global error handler
 *      translates it to a response.
 *
 * Routes that are explicitly public (healthz, metrics, docs) should be
 * registered BEFORE this preHandler is wired, or wire via a route-level
 * opt-out: `request.routeOptions.config.public === true`.
 */

export interface AuthMiddlewareDeps {
  prisma: PrismaClient;
  config: Config;
}

export interface AuthMiddlewareOptions {
  /** When true, proceed without throwing if no token is present. Default false. */
  allowAnonymous?: boolean;
}

/**
 * Extract the bearer token from an Authorization header. Returns undefined if
 * the header is missing or malformed — the caller decides whether that's a 401
 * or anonymous access.
 */
export function extractBearerToken(
  header: string | undefined,
): string | undefined {
  if (!header) return undefined;
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match) return undefined;
  const token = match[1]?.trim();
  return token && token.length > 0 ? token : undefined;
}

/**
 * Resolve an API-key token against the database. Returns the built
 * AuthContext on success, throws {@link AuthError} on any failure.
 *
 * Exported so the middleware and tests can exercise it in isolation.
 */
export async function resolveApiKey(
  token: string,
  prisma: PrismaClient,
): Promise<AuthContext> {
  // Partial unique index on `hash` where `revoked_at IS NULL`, but we also
  // need the full-key argon2 verification. Strategy: look up candidates by
  // prefix (first 8 chars, indexed), then argon2-verify against their hashes.
  // Prefix alone is not a secret, and argon2.verify is constant-work.
  const prefix = token.slice(0, 8);
  const candidates = await prisma.apiKey.findMany({
    where: { prefix, revokedAt: null },
    include: { org: { select: { id: true, tier: true } } },
  });

  for (const candidate of candidates) {
    const ok = await verifyApiKey(token, candidate.hash);
    if (!ok) continue;
    // Best-effort last-used update — don't block on it.
    prisma.apiKey
      .update({
        where: { id: candidate.id },
        data: { lastUsedAt: new Date() },
      })
      .catch(() => {
        /* swallowed; auth already succeeded */
      });
    return buildApiKeyContext({
      apiKeyId: candidate.id,
      orgId: candidate.orgId,
      tier: candidate.org.tier,
      scopes: candidate.scopes as ApiKeyScope[],
      prefix: candidate.prefix,
    });
  }

  throw new AuthError("invalid api key", "api_key_invalid");
}

/**
 * Resolve a Supabase JWT into an {@link AuthContext}. Requires
 * `supabaseProjectRef` in config; throws if missing.
 */
export async function resolveSupabaseJwt(
  token: string,
  config: Config,
  prisma?: PrismaClient,
): Promise<AuthContext> {
  if (!config.supabaseProjectRef) {
    throw new AuthError("jwt auth not configured", "jwt_not_configured");
  }
  const payload = await verifySupabaseJwt(token, {
    projectRef: config.supabaseProjectRef,
    audience: config.supabaseJwtAudience,
  });

  // Best-effort: resolve the user's primary org membership so tRPC routers
  // that need orgId scoping (projects, jobs, etc.) work for session-auth users.
  // Users with no membership stay orgId-less; routers should handle that.
  let orgId: string | undefined;
  let tier: "free" | "pro" | "frontier" | undefined;
  if (prisma && payload.sub) {
    const membership = await prisma.orgMember.findFirst({
      where: { userId: payload.sub },
      orderBy: { createdAt: "asc" },
      include: { org: { select: { id: true, tier: true } } },
    });
    if (membership) {
      orgId = membership.orgId;
      tier = membership.org.tier as "free" | "pro" | "frontier";
    }
  }

  return buildUserContext({
    userId: payload.sub,
    email: payload.email,
    role: payload.role,
    orgId,
    tier,
  });
}

/**
 * Build a Fastify preHandler that populates `req.auth`. Routes marked
 * `{ config: { public: true } }` bypass auth entirely.
 */
export function buildAuthPreHandler(
  deps: AuthMiddlewareDeps,
  opts: AuthMiddlewareOptions = {},
) {
  return async function authPreHandler(
    req: FastifyRequest,
    _reply: FastifyReply,
  ): Promise<void> {
    // Opt-out for public routes (healthz, metrics, docs, openapi.json).
    const routeConfig = req.routeOptions?.config as
      | { public?: boolean }
      | undefined;
    if (routeConfig?.public) return;

    // tRPC routes get pass-through auth: if a Bearer token is present we
    // resolve `req.auth` so `publicProcedure`/`protectedProcedure` can read
    // it, but a missing token does NOT throw here — tRPC's own
    // `protectedProcedure` middleware will return a properly superjson-
    // encoded UNAUTHORIZED envelope, which the browser tRPC client knows
    // how to decode. Throwing AuthError here would emit plain JSON and
    // confuse the client with "Unable to transform response from server".
    const isTrpcRoute = req.url?.startsWith("/trpc/") ?? false;

    const token = extractBearerToken(req.headers.authorization);
    if (!token) {
      if (opts.allowAnonymous || isTrpcRoute) return;
      throw new AuthError("missing authorization header", "missing_token");
    }

    try {
      if (token.startsWith("pc_")) {
        req.auth = await resolveApiKey(token, deps.prisma);
      } else {
        req.auth = await resolveSupabaseJwt(token, deps.config, deps.prisma);
      }
    } catch (err) {
      // Same logic for invalid/expired tokens on tRPC routes — let the
      // tRPC layer return a proper envelope rather than a plain-JSON 401.
      if (isTrpcRoute) return;
      throw err;
    }
  };
}

/**
 * Register the auth preHandler on a Fastify app. This intentionally uses
 * `addHook('preHandler', …)` rather than `register` so it runs for every
 * route, including nested plugins.
 */
export function registerAuth(
  app: FastifyInstance,
  deps: AuthMiddlewareDeps,
  opts: AuthMiddlewareOptions = {},
): void {
  app.addHook("preHandler", buildAuthPreHandler(deps, opts));
}
