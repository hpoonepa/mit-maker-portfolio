import type { Writable } from 'node:stream';
import pino, { type Logger, type LoggerOptions } from 'pino';

export interface CreateLoggerOptions {
  /** Service name, attached to every log line as `service`. */
  service: string;
  /** Pino log level. Defaults to `LOG_LEVEL` env var or `info`. */
  level?: string;
  /**
   * Optional destination stream. Primarily used for tests. When omitted the
   * logger writes to stdout via pino's default destination (or `pino-pretty`
   * in dev).
   */
  stream?: Writable;
  /**
   * Additional paths to redact on top of {@link REDACT_PATHS}. Each consumer
   * (api, worker) appends its own service-specific secrets here. Paths follow
   * pino's redact syntax (dot-paths, bracketed keys, `*` wildcards).
   */
  extraRedactPaths?: readonly string[];
}

/**
 * Paths that pino will redact from log output. Covers both top-level keys and
 * the standard request-headers shape used by HTTP servers.
 */
export const REDACT_PATHS: readonly string[] = [
  'req.headers.authorization',
  'headers.authorization',
  'authorization',
  'api_key',
  'apiKey',
  'token',
  'password',
  'r2_secret_access_key',
  '*.api_key',
  '*.apiKey',
  '*.token',
  '*.password',
  '*.r2_secret_access_key',
];

function isProd(): boolean {
  return process.env.NODE_ENV === 'production';
}

/**
 * Create a root pino logger for a service. JSON in production, pretty output
 * in development. Sensitive fields are redacted by default.
 */
export function createLogger(opts: CreateLoggerOptions): Logger {
  const level = opts.level ?? process.env.LOG_LEVEL ?? 'info';

  // Merge shared + extra redact paths, deduped, so a consumer can add its own
  // secrets (e.g. STRIPE_SECRET_KEY) without losing the defaults.
  const redactPaths = Array.from(
    new Set([...REDACT_PATHS, ...(opts.extraRedactPaths ?? [])]),
  );

  const baseOptions: LoggerOptions = {
    level,
    base: { service: opts.service },
    redact: {
      paths: redactPaths,
      censor: '[Redacted]',
      remove: false,
    },
    timestamp: pino.stdTimeFunctions.isoTime,
  };

  if (opts.stream) {
    return pino(baseOptions, opts.stream);
  }

  if (!isProd()) {
    // Lazy-require so prod bundles don't have to include pino-pretty.
    try {
      const transport = pino.transport({
        target: 'pino-pretty',
        options: {
          colorize: true,
          translateTime: 'SYS:HH:MM:ss.l',
          ignore: 'pid,hostname',
        },
      });
      return pino(baseOptions, transport);
    } catch {
      // pino-pretty not installed or failed to load; fall back to JSON stdout.
      return pino(baseOptions);
    }
  }

  return pino(baseOptions);
}

/**
 * Create a child logger inheriting the parent's config with extra bindings
 * (e.g. `requestId`, `userId`). Prefer this for request-scoped context.
 */
export function createChildLogger(
  parent: Logger,
  bindings: Record<string, unknown>,
): Logger {
  return parent.child(bindings);
}

export type { Logger } from 'pino';
