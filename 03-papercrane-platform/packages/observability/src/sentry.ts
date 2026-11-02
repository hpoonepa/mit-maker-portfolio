import * as Sentry from '@sentry/node';

export interface InitSentryOptions {
  /** Sentry DSN. When absent, init is a no-op (safe for local/dev). */
  dsn?: string;
  environment: string;
  release?: string;
  /** Percent of transactions to sample for tracing, 0.0 - 1.0. */
  tracesSampleRate?: number;
}

let initialized = false;

/**
 * Initialize Sentry for Node services. Client-side (browser) init for the
 * Next.js web app lives in that app, not here.
 *
 * Safe no-op when no DSN is provided, so local development doesn't send events.
 */
export function initSentry(opts: InitSentryOptions): boolean {
  if (!opts.dsn) {
    return false;
  }

  Sentry.init({
    dsn: opts.dsn,
    environment: opts.environment,
    release: opts.release,
    tracesSampleRate: opts.tracesSampleRate ?? 0.1,
  });

  initialized = true;
  return true;
}

/** Whether `initSentry` has been called with a DSN in this process. */
export function isSentryInitialized(): boolean {
  return initialized;
}

/**
 * Capture an exception with optional structured context. No-op if Sentry was
 * never initialized (e.g. local dev without a DSN).
 */
export function captureException(
  err: unknown,
  context?: Record<string, unknown>,
): string | undefined {
  if (!initialized) {
    return undefined;
  }
  return Sentry.captureException(err, context ? { extra: context } : undefined);
}

/** Re-exported for callers that want direct Sentry API access. */
export { Sentry };
