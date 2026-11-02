import type { FastifyInstance } from "fastify";
import type Redis from "ioredis";
import type { PrismaClient } from "@papercrane/db";
import { buildHealthResponse } from "@papercrane/observability";

export interface HealthzDeps {
  prisma: PrismaClient;
  redis: Redis | null;
}

/**
 * Register `/healthz`. Public (auth-exempt) and rate-limit-exempt so load
 * balancers can probe it cheaply. Returns 200 with a full report when every
 * check passes, 503 with the same shape when any check fails.
 */
export async function registerHealthz(
  app: FastifyInstance,
  deps: HealthzDeps,
): Promise<void> {
  app.get(
    "/healthz",
    {
      config: { public: true, rateLimit: false },
    },
    async (_req, reply) => {
      const checks: Record<string, () => Promise<boolean>> = {
        db: async () => {
          // `SELECT 1` — the cheapest liveness probe Postgres offers.
          await deps.prisma.$queryRaw`SELECT 1`;
          return true;
        },
      };

      if (deps.redis) {
        checks.redis = async () => {
          const pong = await deps.redis!.ping();
          return pong === "PONG";
        };
      }

      const response = await buildHealthResponse(checks);
      void reply.code(response.ok ? 200 : 503).send(response);
    },
  );
}
