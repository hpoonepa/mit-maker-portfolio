import type { FastifyInstance } from "fastify";
import type { PrismaClient } from "@papercrane/db";
import type Redis from "ioredis";
import { buildRequestContext } from "../context.js";

/**
 * Mount the tRPC router under `/trpc`.
 *
 * The @papercrane/trpc package is being built concurrently. Until it exports
 * a router, this module dynamically imports and no-ops if unavailable. Once
 * the router lands, it will be mounted via `@trpc/server/adapters/fastify`
 * with the per-request context.
 *
 * We intentionally keep this file tiny — router logic belongs in the trpc
 * package, not here.
 */

export interface TrpcMountDeps {
  prisma: PrismaClient;
  redis?: Redis | null;
}

interface FastifyTrpcAdapter {
  fastifyTRPCPlugin: unknown;
}

export async function mountTrpc(
  app: FastifyInstance,
  deps: TrpcMountDeps,
): Promise<boolean> {
  let trpcModule: { createRouter?: () => unknown; appRouter?: unknown };
  try {
    trpcModule = (await import("@papercrane/trpc")) as typeof trpcModule;
  } catch {
    app.log.info(
      "@papercrane/trpc not available; skipping tRPC mount (REST only)",
    );
    return false;
  }

  const router =
    typeof trpcModule.createRouter === "function"
      ? trpcModule.createRouter()
      : trpcModule.appRouter;
  if (!router) {
    app.log.info("@papercrane/trpc exports no router yet; skipping tRPC mount");
    return false;
  }

  let adapter: FastifyTrpcAdapter;
  try {
    const moduleName = "@trpc/server/adapters/fastify";
    adapter = (await import(
      /* @vite-ignore */ moduleName
    )) as unknown as FastifyTrpcAdapter;
  } catch {
    app.log.warn(
      "@trpc/server not installed in api package; skipping tRPC mount",
    );
    return false;
  }

  const plugin = adapter.fastifyTRPCPlugin as (
    app: FastifyInstance,
    opts: Record<string, unknown>,
  ) => Promise<void>;

  await app.register(plugin, {
    prefix: "/trpc",
    trpcOptions: {
      router,
      createContext: ({ req }: { req: Parameters<typeof buildRequestContext>[0] }) =>
        buildRequestContext(req, { prisma: deps.prisma, redis: deps.redis }),
    },
  });
  app.log.info("tRPC router mounted at /trpc");
  return true;
}
