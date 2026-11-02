import { z } from "zod";

/**
 * API service configuration.
 *
 * Loaded from `process.env` at boot, validated with zod, and then treated as
 * read-only for the lifetime of the process. Missing required variables in
 * production are fatal — we prefer to fail fast at startup rather than at the
 * first request that touches the missing value.
 */

const NodeEnvSchema = z
  .enum(["development", "test", "staging", "production"] as const)
  .default("development");

const LogLevelSchema = z
  .enum(["trace", "debug", "info", "warn", "error", "fatal"] as const)
  .default("info");

/**
 * Schema for all env vars the API reads. Vars that are required only in
 * production are marked optional here; we enforce their presence later via
 * {@link assertProductionConfig}.
 */
const ConfigSchema = z.object({
  nodeEnv: NodeEnvSchema,
  logLevel: LogLevelSchema,
  port: z.coerce.number().int().min(1).max(65535).default(3001),
  host: z.string().default("0.0.0.0"),

  // Database
  databaseUrl: z.string().url().optional(),

  // Redis
  redisUrl: z.string().optional(),

  // Supabase (for JWT verification)
  supabaseProjectRef: z.string().optional(),
  supabaseJwtAudience: z.string().default("authenticated"),

  // Observability
  sentryDsn: z.string().optional(),
  sentryEnvironment: z.string().optional(),
  sentryTracesSampleRate: z.coerce.number().min(0).max(1).default(0.1),

  // Security / auth
  apiKeyPepper: z.string().optional(),

  // CORS — comma-separated allowlist. Wildcard "*" is rejected in production
  // by assertProductionConfig below; dev defaults cover the marketing site
  // (:3000), api self (:3001), product app (:3002), and worker (:3003).
  corsOrigin: z
    .string()
    .default(
      "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003",
    ),

  // App URLs (web=marketing, app=authenticated dashboard)
  appUrl: z.string().url().default("http://localhost:3002"),
  webUrl: z.string().url().default("http://localhost:3000"),

  // Stripe — billing integration
  // Secret key is required for billing routes to mount. The price ids are
  // required to map Checkout/Portal/Webhook events onto the correct tier in
  // the org row; they are optional at boot so local dev without billing can
  // still run (routes log a warning and skip mount instead).
  stripeSecretKey: z.string().optional(),
  stripeWebhookSecret: z.string().optional(),
  stripePriceProMonthly: z.string().optional(),
  stripePriceProAnnual: z.string().optional(),
  stripePriceSeatAddon: z.string().optional(),
  stripePricePack10k: z.string().optional(),
});

export type Config = z.infer<typeof ConfigSchema>;

interface DatabaseEnv {
  NODE_ENV?: string;
  DATABASE_URL?: string;
  DIRECT_URL?: string;
}

/**
 * A local API server is a persistent process, so Supabase's session pool is
 * the appropriate runtime connection. Transaction pooling remains the
 * production default for deployments that explicitly configure it.
 */
export function preferSessionPoolForDevServer(
  env: DatabaseEnv = process.env,
): void {
  if ((env.NODE_ENV ?? "development") === "development" && env.DIRECT_URL) {
    env.DATABASE_URL = env.DIRECT_URL;
  }
}

/**
 * Keys that MUST be present when NODE_ENV=production. Local dev can omit these
 * (we stub checks and no-op external calls), but prod should never boot without
 * them. Listed explicitly rather than computed so reviewers can audit.
 */
const PRODUCTION_REQUIRED: readonly (keyof Config)[] = [
  "databaseUrl",
  "redisUrl",
  "supabaseProjectRef",
];

/**
 * Load config from an env record (defaults to {@link process.env}). Throws a
 * descriptive error if validation fails — the caller is expected to crash the
 * process rather than attempt to recover.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const nodeEnv = env.NODE_ENV ?? "development";
  const parsed = ConfigSchema.safeParse({
    nodeEnv,
    logLevel: env.LOG_LEVEL,
    port: env.PORT,
    host: env.HOST,
    databaseUrl: env.DATABASE_URL,
    redisUrl:
      env.REDIS_URL ||
      (nodeEnv === "production" ? undefined : "redis://localhost:6379"),
    supabaseProjectRef: env.SUPABASE_PROJECT_REF,
    supabaseJwtAudience: env.SUPABASE_JWT_AUDIENCE,
    sentryDsn: env.SENTRY_DSN,
    sentryEnvironment: env.SENTRY_ENVIRONMENT ?? env.NODE_ENV,
    sentryTracesSampleRate: env.SENTRY_TRACES_SAMPLE_RATE,
    apiKeyPepper: env.API_KEY_PEPPER,
    corsOrigin: env.CORS_ORIGIN,
    appUrl: env.NEXT_PUBLIC_APP_URL ?? env.APP_URL,
    webUrl: env.NEXT_PUBLIC_WEB_URL ?? env.WEB_URL ?? env.NEXT_PUBLIC_APP_URL,
    stripeSecretKey: env.STRIPE_SECRET_KEY,
    stripeWebhookSecret: env.STRIPE_WEBHOOK_SECRET,
    stripePriceProMonthly: env.STRIPE_PRICE_PRO_MONTHLY,
    stripePriceProAnnual: env.STRIPE_PRICE_PRO_ANNUAL,
    stripePriceSeatAddon: env.STRIPE_PRICE_SEAT_ADDON,
    stripePricePack10k: env.STRIPE_PRICE_PACK_10K,
  });

  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `${i.path.join(".") || "<root>"}: ${i.message}`)
      .join("; ");
    throw new Error(`invalid API config: ${issues}`);
  }

  const cfg = parsed.data;
  assertProductionConfig(cfg);
  return cfg;
}

function assertProductionConfig(cfg: Config): void {
  if (cfg.nodeEnv !== "production") return;
  const missing = PRODUCTION_REQUIRED.filter((k) => !cfg[k]);
  if (missing.length > 0) {
    throw new Error(
      `missing required env vars in production: ${missing.join(", ")}`,
    );
  }
  // Wildcard CORS in production lets any site phish authenticated requests.
  if (cfg.corsOrigin === "*" || cfg.corsOrigin.includes("*")) {
    throw new Error(
      "CORS_ORIGIN must be an explicit comma-separated allowlist in production (no wildcards)",
    );
  }
}
