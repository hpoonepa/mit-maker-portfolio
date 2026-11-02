/**
 * API-side logger factory.
 *
 * Re-exports the shared pino logger from `@papercrane/observability` with the
 * API's service name baked in and an extended redact list specific to the
 * API surface (Supabase service role key, Stripe secret, cookies, etc.).
 *
 * Keep redact additions in sync with `apps/api/src/config.ts` — anything that
 * is loaded from env as a secret should be redacted here too.
 */
import {
  createLogger,
  REDACT_PATHS,
  type Logger,
  type CreateLoggerOptions,
} from "@papercrane/observability";

/**
 * Extra paths to redact on top of the shared `REDACT_PATHS` set. Covers HTTP
 * headers (`req.headers.*`, `res.headers.*`, top-level `headers.*`), bodies
 * (`req.body.*`, top-level keys), and arbitrary nested objects (`*.NAME`).
 */
export const API_REDACT_PATHS: readonly string[] = [
  // HTTP headers
  'req.headers.cookie',
  'req.headers["set-cookie"]',
  'res.headers["set-cookie"]',
  'headers.cookie',
  'headers["set-cookie"]',
  "cookie",
  "set-cookie",

  // Common credential field names
  "secret",
  "apikey",
  "*.secret",
  "*.apikey",
  "*.cookie",

  // Supabase / Stripe / providers (env-style + camelCase variants)
  "*.SUPABASE_SERVICE_ROLE_KEY",
  "*.STRIPE_SECRET_KEY",
  "*.STRIPE_WEBHOOK_SECRET",
  "*.MODAL_TOKEN_SECRET",
  "*.VASTAI_API_KEY",
  "*.RUNPOD_API_KEY",
  "supabaseServiceRoleKey",
  "stripeSecretKey",
  "stripeWebhookSecret",

  // Request body credential keys
  "req.body.password",
  "req.body.token",
  "req.body.secret",
  "req.body.apiKey",
  "req.body.api_key",
];

/** Effective redact list applied to the API logger (shared + extras, deduped). */
export const ALL_REDACT_PATHS: readonly string[] = Array.from(
  new Set([...REDACT_PATHS, ...API_REDACT_PATHS]),
);

/**
 * Create the API root logger. Bound with `service: "papercrane-api"` and the
 * extended redact list. Tests can pass a `stream` to capture output.
 */
export function createApiLogger(
  opts: Omit<CreateLoggerOptions, "service" | "extraRedactPaths"> = {},
): Logger {
  return createLogger({
    service: "papercrane-api",
    extraRedactPaths: API_REDACT_PATHS,
    ...opts,
  });
}

export type { Logger };
