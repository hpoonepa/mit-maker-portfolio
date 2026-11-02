/**
 * API `/healthz` route — production probe shape.
 *
 *   { ok, db, redis, version, uptime_s }
 *
 * Exposes a single GET endpoint that pings Postgres and (optionally) Redis in
 * parallel. Returns 200 when every wired dependency is healthy, 503 otherwise.
 *
 * The route is marked `public` and `rateLimit: false` so load balancers and
 * uptime probes don't count against per-org limits and don't need an API key.
 *
 * NOTE: a separate `routes/rest/healthz.ts` historically registered a richer
 * shape used by the OpenAPI spec. This module exposes the simpler probe shape
 * required by Wave 8 observability and is the canonical mount target — the
 * older route can be retired once consumers migrate.
 */
import type { FastifyInstance } from "fastify";
import type Redis from "ioredis";
import type { PrismaClient } from "@papercrane/db";

export interface HealthDeps {
  prisma: PrismaClient;
  redis: Redis | null;
  /** Service version (defaults to `process.env.APP_VERSION` or "0.0.0"). */
  version?: string;
}

export interface HealthBody {
  ok: boolean;
  db: boolean;
  redis: boolean;
  version: string;
  uptime_s: number;
}

const STARTED_AT_MS = Date.now();

async function pingDb(prisma: PrismaClient): Promise<boolean> {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return true;
  } catch {
    return false;
  }
}

async function pingRedis(redis: Redis | null): Promise<boolean> {
  if (!redis) return false;
  try {
    const pong = await redis.ping();
    return pong === "PONG";
  } catch {
    return false;
  }
}

/**
 * Register `GET /healthz` on the given Fastify instance. Idempotent only at
 * the caller level — Fastify will throw on duplicate routes, so don't call
 * twice in the same server.
 */
export async function registerHealth(
  app: FastifyInstance,
  deps: HealthDeps,
): Promise<void> {
  const version =
    deps.version ?? process.env.APP_VERSION ?? process.env.npm_package_version ?? "0.0.0";

  app.get(
    "/healthz",
    { config: { public: true, rateLimit: false } },
    async (_req, reply) => {
      const [db, redis] = await Promise.all([
        pingDb(deps.prisma),
        pingRedis(deps.redis),
      ]);

      // `redis` is only required when wired. If `deps.redis` is null we treat
      // it as "not applicable" — the probe returns `redis: false` but doesn't
      // fail the overall check. This matches dev where Redis is optional.
      const redisRequired = deps.redis !== null;
      const ok = db && (!redisRequired || redis);

      const body: HealthBody = {
        ok,
        db,
        redis,
        version,
        uptime_s: Math.floor((Date.now() - STARTED_AT_MS) / 1000),
      };
      void reply.code(ok ? 200 : 503).send(body);
    },
  );
}
