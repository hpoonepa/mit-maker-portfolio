import Fastify, { type FastifyInstance, type FastifyServerOptions } from "fastify";
import cors from "@fastify/cors";
import sensible from "@fastify/sensible";
import Redis from "ioredis";
import { prisma as defaultPrisma, type PrismaClient } from "@papercrane/db";
import {
  createStripeClient,
  type BillingPriceEnv,
  type Stripe,
} from "@papercrane/billing";
// `registerBillingRoutes` is Fastify-shaped glue and lives in this app. It
// wires the pure handlers from @papercrane/billing into HTTP routes.
import { registerBillingRoutes } from "./routes/rest/billing.js";
import { loadConfig, type Config } from "./config.js";
import { errorHandler } from "./middleware/errorHandler.js";
import { registerAuth } from "./middleware/auth.js";
import { registerRateLimit } from "./middleware/rateLimit.js";
import { ssePlugin } from "./plugins/sse.js";
import { openapiPlugin } from "./plugins/openapi.js";
import { registerHealth } from "./observability/health.js";
import { registerRequestId } from "./observability/request-id.js";
import { registerApiKeyRoutes } from "./routes/rest/apiKeys.js";
import { registerUsageRoutes } from "./routes/rest/usage.js";
import { registerWebhookRoutes } from "./routes/rest/webhooks.js";
import { mountTrpc } from "./routes/trpc.js";

/**
 * Build a configured Fastify instance. Boots all middleware, plugins, and
 * routes but does NOT call `listen()` — the caller (normally `server.ts`)
 * drives the lifecycle.
 *
 * Dependency injection points:
 *   - `prisma`  — default is the singleton from @papercrane/db; tests inject mocks
 *   - `redis`   — default is a fresh ioredis from config.redisUrl, or null if unset
 *   - `config`  — default is loaded from process.env via loadConfig()
 */

export interface BuildServerOptions {
  config?: Config;
  prisma?: PrismaClient;
  redis?: Redis | null;
  fastifyOpts?: FastifyServerOptions;
}

export async function buildServer(
  options: BuildServerOptions = {},
): Promise<FastifyInstance> {
  const config = options.config ?? loadConfig();
  const prisma = options.prisma ?? defaultPrisma;
  const redis =
    options.redis !== undefined
      ? options.redis
      : config.redisUrl
        ? new Redis(config.redisUrl, { lazyConnect: true, maxRetriesPerRequest: 3 })
        : null;

  const app = Fastify({
    logger: { level: config.logLevel },
    requestIdHeader: "x-request-id",
    trustProxy: true,
    // tRPC batches encode procedure names in one route parameter. The
    // dashboard's normal seven-query batch is longer than Fastify's 100-char
    // default and otherwise falls through as a misleading 404.
    maxParamLength: 1000,
    ...options.fastifyOpts,
  });

  // Request-id hook runs first so every downstream log line and Sentry event
  // carries the id (incoming `x-request-id` is preserved, otherwise UUIDv7).
  registerRequestId(app);

  // Core plugins first — order matters: sensible → cors → sse → openapi.
  await app.register(sensible);
  // CORS — allowlist origins. CORS_ORIGIN is a comma-separated list. The
  // dashboard (NEXT_PUBLIC_APP_URL) and marketing site (NEXT_PUBLIC_WEB_URL)
  // are always allowed in addition to the configured list. Same-origin /
  // server-to-server (no Origin header) requests pass through unchanged.
  const allowedOrigins = new Set(
    [
      ...config.corsOrigin.split(",").map((s) => s.trim()).filter(Boolean),
      config.appUrl,
      config.webUrl,
    ],
  );
  await app.register(cors, {
    origin: (origin, cb) => {
      if (!origin) return cb(null, true);
      if (allowedOrigins.has(origin)) return cb(null, true);
      cb(new Error("origin not allowed by CORS policy"), false);
    },
    credentials: true,
  });
  await app.register(ssePlugin);
  await app.register(openapiPlugin, { publicUrl: config.appUrl });

  // Public routes (healthz) must be registered BEFORE auth hook attaches so
  // they can opt out via `config.public`. The auth hook checks the flag;
  // registration order isn't strictly required but keeps intent obvious.
  await registerHealth(app, { prisma, redis });

  // Dev-only object-storage stub. tRPC `presignPut` returns
  // http://localhost:3001/dev-stub/put/<key> when no real R2 creds are wired;
  // browser PUTs the file, we persist it under `/tmp/papercrane-dev-stub`,
  // and a later GET (server-side `commitUpload` revalidates ATOM records +
  // checksum) reads it back. Filesystem-backed so the bytes survive tsx-watch
  // restarts. NEVER mounted in production (gated on NODE_ENV).
  if (config.nodeEnv !== "production") {
    // Dev-only object-storage stub (emulates R2 presigned PUT/GET on local
    // disk). Extracted to `registerDevStub` so it can be unit-tested; the write
    // path re-ensures its directory every request because /tmp is volatile.
    const { registerDevStub } = await import("./routes/rest/devStub.js");
    await registerDevStub(app);
  }

  // Global error handler — set before routes so thrown errors during route
  // registration itself don't escape.
  app.setErrorHandler(errorHandler);

  // Auth + rate limit run on every non-public route.
  registerAuth(app, { prisma, config });
  if (redis) {
    registerRateLimit(app, { redis });
  } else {
    app.log.warn("redis not configured; rate limiting disabled");
  }

  // Authenticated REST routes.
  await registerApiKeyRoutes(app, { prisma });
  await registerUsageRoutes(app, { prisma });
  await registerWebhookRoutes(app, { prisma });

  // tRPC (dynamically mounted when the package is available).
  await mountTrpc(app, { prisma, redis });

  // Billing routes — guarded by the presence of STRIPE_SECRET_KEY. In dev we
  // intentionally allow the API to boot without Stripe so contributors without
  // billing creds can still iterate on everything else. In production the
  // `assertProductionConfig` in config.ts will have rejected a missing key
  // before we get here (once Stripe is in the required list).
  const stripe = buildStripeClient(app, config);
  if (stripe && config.stripeWebhookSecret) {
    const priceEnv: BillingPriceEnv = {
      STRIPE_PRICE_PRO_MONTHLY: config.stripePriceProMonthly,
      STRIPE_PRICE_PRO_ANNUAL: config.stripePriceProAnnual,
      STRIPE_PRICE_SEAT_ADDON: config.stripePriceSeatAddon,
      STRIPE_PRICE_PACK_10K: config.stripePricePack10k,
    };
    await registerBillingRoutes(app, {
      prisma,
      redis,
      stripe,
      priceEnv,
      webhookSecret: config.stripeWebhookSecret,
    });
    app.log.info("billing routes mounted at /v1/billing/*");
  } else {
    app.log.warn(
      "STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET missing; skipping billing mount",
    );
  }

  return app;
}

/**
 * Build a single Stripe client per process. Returns null when the secret key
 * is unset (dev bootstrap without billing). Tests can inject their own client
 * via a different buildServer fork if needed.
 */
function buildStripeClient(
  app: FastifyInstance,
  config: Config,
): Stripe | null {
  if (!config.stripeSecretKey) {
    app.log.warn(
      "STRIPE_SECRET_KEY not set; Stripe client not initialized (dev mode)",
    );
    return null;
  }
  return createStripeClient({ secretKey: config.stripeSecretKey });
}

export default buildServer;
export { loadConfig } from "./config.js";
export type { Config } from "./config.js";
