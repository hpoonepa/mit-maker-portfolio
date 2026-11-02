/**
 * Worker-side logger factory.
 *
 * Re-exports the shared pino logger from `@papercrane/observability` with the
 * worker's service name baked in and an extended redact list specific to the
 * worker's secret surface (provider tokens, Modal/Vast/Runpod creds, etc.).
 */
import {
  createLogger,
  REDACT_PATHS,
  type Logger,
  type CreateLoggerOptions,
} from '@papercrane/observability';

/**
 * Worker-specific redact additions on top of the shared `REDACT_PATHS` set.
 * Keep in sync with `apps/worker/src/config.ts` — every secret loaded from
 * env should be redacted here too.
 */
export const WORKER_REDACT_PATHS: readonly string[] = [
  // Generic
  'secret',
  'apikey',
  'cookie',
  '*.secret',
  '*.apikey',
  '*.cookie',

  // Provider env-var names
  '*.MODAL_TOKEN_ID',
  '*.MODAL_TOKEN_SECRET',
  '*.VASTAI_API_KEY',
  '*.RUNPOD_API_KEY',
  '*.SUPABASE_SERVICE_ROLE_KEY',
  '*.STRIPE_SECRET_KEY',
  '*.STRIPE_WEBHOOK_SECRET',

  // Provider config camelCase variants
  '*.tokenSecret',
  '*.tokenId',
  'providers.modal.tokenSecret',
  'providers.modal.tokenId',
  'providers.vastai.apiKey',
  'providers.runpod.apiKey',

  // Webhook signing secrets stored on the job row
  'webhookSecret',
  '*.webhookSecret',
];

/** Effective redact list applied to the worker logger. */
export const ALL_REDACT_PATHS: readonly string[] = Array.from(
  new Set([...REDACT_PATHS, ...WORKER_REDACT_PATHS]),
);

/**
 * Create the worker root logger. Bound with `service: "papercrane-worker"`
 * and the extended redact list.
 */
export function createWorkerLogger(
  opts: Omit<CreateLoggerOptions, 'service' | 'extraRedactPaths'> = {},
): Logger {
  return createLogger({
    service: 'papercrane-worker',
    extraRedactPaths: WORKER_REDACT_PATHS,
    ...opts,
  });
}

export type { Logger };
