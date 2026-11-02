/**
 * Zod schemas describing each service's environment surface.
 *
 * Goals:
 *   - Crash-fast at startup with a human-readable error if a required var is
 *     missing or malformed (Wave 15 — beta tester UX).
 *   - Warn (don't fail) on optional integrations so local dev keeps working
 *     without Stripe/Resend/Modal/R2.
 *   - Never echo a value in error output — only var names + descriptions.
 *
 * Every required field carries a `.describe(...)` string. The parser uses that
 * string to render the "Missing required:" block, so reviewers should keep the
 * description short and actionable ("Supabase Postgres connection string").
 */

import { z } from "zod";

// ---------- shared atoms ----------

const NodeEnv = z
  .enum(["development", "test", "staging", "production"] as const)
  .default("development");

const url = (description: string) =>
  z.string().url(`must be a valid URL`).describe(description);

const nonEmpty = (description: string) =>
  z.string().min(1, "must be non-empty").describe(description);

// `optional()` only treats `undefined` as missing; an empty string in
// `.env.local` still hits the validator and fails. Coerce empty → undefined
// so soft-required dev vars (Stripe, Redis pre-stub) can stay listed in
// `.env.local` without breaking boot. The inner schema MUST be `.optional()`
// itself so the resulting `undefined` is accepted by the validator.
const emptyToUndefOptional = <T extends z.ZodTypeAny>(s: T) =>
  z.preprocess((v) => (v === "" ? undefined : v), s.optional());

const stripeSecret = (description: string) =>
  emptyToUndefOptional(
    z
      .string()
      .regex(
        /^sk_(test|live)_/,
        'must start with "sk_test_" or "sk_live_"',
      )
      .describe(description),
  );

const stripeWebhookSecret = (description: string) =>
  emptyToUndefOptional(
    z
      .string()
      .regex(/^whsec_/, 'must start with "whsec_"')
      .describe(description),
  );

const stripePublishableKey = (description: string) =>
  z
    .string()
    .regex(
      /^pk_(test|live)_/,
      'must start with "pk_test_" or "pk_live_"',
    )
    .describe(description);

// ---------- API service ----------

/**
 * `apps/api` — the Fastify backend. Required vars MUST be present in every
 * environment (incl. local dev) because the API touches Supabase + Postgres
 * on every request. Stripe is technically optional in dev (warning emitted)
 * but enforced in production via `productionRequired`.
 */
export const ApiEnvSchema = z.object({
  NODE_ENV: NodeEnv,

  // --- required: data layer ---
  DATABASE_URL: url("Supabase Postgres connection string (pooled)"),
  DIRECT_URL: url("Supabase Postgres connection string (direct, for migrations)"),
  // Soft-required in dev: empty string → undefined, lets the API boot without
  // a real Redis. Lazy-connect Redis client (apps/api/src/index.ts) tolerates
  // missing URL — queue calls fall through to in-process resolution.
  REDIS_URL: emptyToUndefOptional(
    z.string().min(1).describe("Redis URL for queue + caching (e.g. redis://...)"),
  ),

  // --- required: auth ---
  NEXT_PUBLIC_SUPABASE_URL: url("Supabase project URL (https://<ref>.supabase.co)"),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: nonEmpty(
    "Supabase anon/public key (for client-side calls)",
  ),
  SUPABASE_SERVICE_ROLE_KEY: nonEmpty(
    "Supabase service-role key (server-side only, NEVER expose to clients)",
  ),
  SUPABASE_PROJECT_REF: z.string().optional(),

  // --- required-with-warning: billing ---
  // Soft-required: parser warns when missing in dev so billing routes stay
  // mountable; production still requires them via `productionRequired`.
  STRIPE_SECRET_KEY: stripeSecret(
    "Stripe secret key — required for billing routes",
  ).optional(),
  STRIPE_WEBHOOK_SECRET: stripeWebhookSecret(
    "Stripe webhook signing secret — required to verify Stripe events",
  ).optional(),

  // --- optional: integrations ---
  SENTRY_DSN: z.preprocess((v) => (typeof v === "string" && v.trim() === "" ? undefined : v), z.string().url().optional()).describe("Sentry DSN for error reporting"),
  SENTRY_ENVIRONMENT: z.string().optional(),
  SENTRY_TRACES_SAMPLE_RATE: z.coerce.number().min(0).max(1).optional(),
  RESEND_API_KEY: z.string().optional().describe("Resend API key for transactional email"),
  MODAL_TOKEN_ID: z.string().optional(),
  MODAL_TOKEN_SECRET: z.string().optional(),
  MODAL_CREDENTIAL_ENCRYPTION_KEY: z.string().optional(),
  MODAL_WORKSPACE: z.string().optional(),
  MODAL_ENVIRONMENT: z.string().optional(),
  R2_ACCOUNT_ID: z.string().optional(),
  R2_ACCESS_KEY_ID: z.string().optional(),
  R2_SECRET_ACCESS_KEY: z.string().optional(),
  R2_BUCKET: z.string().optional(),
  OPENAI_API_KEY: z.string().optional(),

  // --- optional: server tuning ---
  PORT: z.coerce.number().int().min(1).max(65535).optional(),
  HOST: z.string().optional(),
  LOG_LEVEL: z.string().optional(),
  CORS_ORIGIN: z.string().optional(),
  NEXT_PUBLIC_APP_URL: z.string().url().optional(),
  APP_URL: z.string().url().optional(),
});

// ---------- Worker service ----------

/**
 * `apps/worker` — the BullMQ worker. Per Wave 10, when REDIS_URL is missing
 * AND NODE_ENV !== production, we fall back to an in-memory queue. So
 * REDIS_URL is "soft required": warn in dev, enforce in prod.
 */
export const WorkerEnvSchema = z.object({
  NODE_ENV: NodeEnv,

  DATABASE_URL: url("Postgres connection string for the worker"),

  // Soft-required: dev fallback is the in-memory queue (Wave 10). We coerce
  // empty string → undefined so an unset `REDIS_URL=` line in .env.local
  // doesn't trip `nonEmpty` validation — mirrors the api schema's handling.
  REDIS_URL: emptyToUndefOptional(
    z.string().min(1).describe("Redis URL for BullMQ — falls back to in-memory in dev"),
  ),

  // GPU providers
  MODAL_TOKEN_ID: z.string().optional(),
  MODAL_TOKEN_SECRET: z.string().optional(),
  MODAL_CREDENTIAL_ENCRYPTION_KEY: z.string().optional(),
  PAPERCRANE_MODAL_AUTO_DEPLOY: z.enum(["0", "1", "true", "false"]).optional(),
  MODAL_WORKSPACE: z.string().optional(),
  MODAL_ENVIRONMENT: z.string().optional(),
  VASTAI_API_KEY: z.string().optional(),
  RUNPOD_API_KEY: z.string().optional(),

  // Storage
  R2_ACCOUNT_ID: z.string().optional(),
  R2_ACCESS_KEY_ID: z.string().optional(),
  R2_SECRET_ACCESS_KEY: z.string().optional(),
  R2_BUCKET: z.string().optional(),

  // Observability + email
  SENTRY_DSN: z.preprocess((v) => (typeof v === "string" && v.trim() === "" ? undefined : v), z.string().url().optional()),
  RESEND_API_KEY: z.string().optional(),

  LOG_LEVEL: z.string().optional(),
  PORT_HEALTH: z.coerce.number().int().min(1).max(65535).optional(),
});

// ---------- App (authenticated Next.js) ----------

/**
 * `apps/app` — the authenticated dashboard. NEXT_PUBLIC_* vars are exposed to
 * the client at build time, so anything sensitive lives in server-only vars
 * (which we only validate in `getServerEnv`, not at module import time).
 */
export const AppPublicEnvSchema = z.object({
  NEXT_PUBLIC_SUPABASE_URL: url("Supabase project URL"),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: nonEmpty("Supabase anon/public key"),
  NEXT_PUBLIC_APP_URL: url("Public URL where the app is served"),

  NEXT_PUBLIC_API_BASE_URL: z.string().url().optional(),
  NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY: stripePublishableKey(
    "Stripe publishable key for client-side checkout",
  ).optional(),
});

export const AppServerEnvSchema = z.object({
  // Server-side only — never bundle into the client.
  SUPABASE_SERVICE_ROLE_KEY: nonEmpty(
    "Supabase service-role key (server-side calls only)",
  ),
});

// ---------- Web (marketing site) ----------

/**
 * `apps/web` — the marketing site. Almost nothing required; we just want a
 * canonical site URL for canonical tags / sitemaps. Defaults to localhost so
 * `pnpm dev` works with zero config.
 */
export const WebEnvSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z
    .string()
    .url()
    .default("http://localhost:3000")
    .describe("Public URL where the marketing site is served"),
});

// ---------- production-required overlay ----------

/**
 * Vars that MUST be present when NODE_ENV=production, even if they're marked
 * optional in the schema above. Listed explicitly per service so reviewers can
 * audit the prod surface in one glance.
 */
export const productionRequired: Record<string, readonly string[]> = {
  api: [
    "DATABASE_URL",
    "DIRECT_URL",
    "REDIS_URL",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "SUPABASE_PROJECT_REF",
    "SUPABASE_SERVICE_ROLE_KEY",
    "MODAL_CREDENTIAL_ENCRYPTION_KEY",
  ],
  worker: [
    "DATABASE_URL",
    "REDIS_URL",
    "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET",
    "MODAL_CREDENTIAL_ENCRYPTION_KEY",
  ],
  app: [
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_APP_URL",
  ],
  web: [],
};

/**
 * Vars whose absence is non-fatal but worth a startup warning in any
 * environment (so devs notice missing integrations instead of finding out
 * mid-feature). Renderer dedupes against `productionRequired`.
 */
export const warnIfMissing: Record<string, readonly string[]> = {
  api: [
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SENTRY_DSN",
    "RESEND_API_KEY",
  ],
  worker: ["REDIS_URL", "MODAL_TOKEN_ID", "SENTRY_DSN"],
  app: ["NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY"],
  web: ["NEXT_PUBLIC_SITE_URL"],
};
