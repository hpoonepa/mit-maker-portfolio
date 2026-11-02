import type { FastifyInstance } from "fastify";
import fp from "fastify-plugin";

/**
 * OpenAPI + Swagger UI plugin.
 *
 * The final plan mounts `trpc-to-openapi` to generate the spec from the
 * @papercrane/trpc router at runtime. That package is being built
 * concurrently; until its router factory is exported, we fall back to a
 * minimal hand-rolled spec covering the handful of REST endpoints that ship
 * independently (healthz, keys, usage, webhooks).
 *
 * Swagger UI — mounted at `/docs` — is registered only if the `@fastify/swagger`
 * and `@fastify/swagger-ui` modules resolve. Missing deps are logged and the
 * plugin no-ops. Prod still serves the spec JSON at `/openapi.json`.
 */

export interface OpenApiPluginOptions {
  /** Base URL to advertise in the OpenAPI servers list. */
  publicUrl?: string;
  /** Whether to mount `/docs` swagger UI. Default true outside production. */
  mountUI?: boolean;
}

interface TrpcModule {
  createRouter?: () => unknown;
  appRouter?: unknown;
}

async function loadTrpcRouter(): Promise<unknown | null> {
  try {
    const mod = (await import("@papercrane/trpc")) as TrpcModule;
    if (typeof mod.createRouter === "function") {
      return mod.createRouter();
    }
    if (mod.appRouter) return mod.appRouter;
    return null;
  } catch {
    return null;
  }
}

/**
 * Build a minimal fallback OpenAPI 3.0 document when the tRPC router isn't
 * available. Covers the endpoints we hand-wrote in `src/routes/rest/*`.
 */
function buildFallbackSpec(publicUrl: string): Record<string, unknown> {
  return {
    openapi: "3.0.3",
    info: {
      title: "Paper Crane API",
      version: "0.1.0",
      description:
        "Public REST surface for Paper Crane. Generated from tRPC routers in production; hand-rolled fallback while scaffolding.",
    },
    servers: [{ url: publicUrl }],
    paths: {
      "/healthz": {
        get: {
          summary: "Liveness + dependency check",
          responses: { "200": { description: "ok" }, "503": { description: "degraded" } },
        },
      },
      "/v1/keys": {
        get: { summary: "List API keys" },
        post: { summary: "Issue API key" },
      },
      "/v1/keys/{id}": {
        delete: { summary: "Revoke API key" },
      },
      "/v1/usage/current": { get: { summary: "Current billing-period usage" } },
      "/v1/usage/history": { get: { summary: "Historical usage" } },
      "/v1/webhooks": {
        get: { summary: "List webhook subscriptions" },
        post: { summary: "Create webhook subscription" },
      },
      "/v1/webhooks/{id}": {
        delete: { summary: "Delete webhook subscription" },
      },
    },
  };
}

export const openapiPlugin = fp(async function openapiPluginImpl(
  app: FastifyInstance,
  opts: OpenApiPluginOptions = {},
): Promise<void> {
  const publicUrl = opts.publicUrl ?? "http://localhost:3001";
  const mountUI = opts.mountUI ?? process.env.NODE_ENV !== "production";

  // Attempt to build spec from tRPC router; fall back if unavailable.
  const trpcRouter = await loadTrpcRouter();
  let spec: Record<string, unknown> = buildFallbackSpec(publicUrl);

  if (trpcRouter) {
    try {
      // `trpc-to-openapi` is optional — guard its import with a dynamic
      // module specifier so bundlers don't hard-fail when it's absent.
      const moduleName = "trpc-to-openapi";
      const mod = (await import(
        /* @vite-ignore */ moduleName
      )) as {
        generateOpenApiDocument: (
          router: unknown,
          opts: Record<string, unknown>,
        ) => Record<string, unknown>;
      };
      spec = mod.generateOpenApiDocument(trpcRouter, {
        title: "Paper Crane API",
        version: "0.1.0",
        baseUrl: publicUrl,
      });
    } catch (err) {
      app.log.warn(
        { err },
        "trpc-to-openapi unavailable; falling back to hand-rolled spec",
      );
    }
  }

  app.get(
    "/openapi.json",
    { config: { public: true } },
    async () => spec,
  );

  if (mountUI) {
    try {
      const swaggerName = "@fastify/swagger";
      const swaggerUiName = "@fastify/swagger-ui";
      const swagger = (await import(/* @vite-ignore */ swaggerName)) as {
        default: unknown;
      };
      const swaggerUi = (await import(/* @vite-ignore */ swaggerUiName)) as {
        default: unknown;
      };
      await app.register(swagger.default as never, {
        mode: "static",
        specification: { document: spec },
      });
      await app.register(swaggerUi.default as never, {
        routePrefix: "/docs",
        uiConfig: { docExpansion: "list", deepLinking: false },
      });
    } catch (err) {
      app.log.warn(
        { err },
        "swagger UI packages not installed; /docs disabled",
      );
    }
  }
});
