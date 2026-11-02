/**
 * Server-side (Node runtime) Sentry initialization for the Next.js app.
 *
 * Loaded from `instrumentation.ts` `register()`. Mirrors the API/worker
 * pattern: gated on `SENTRY_DSN`, dynamic-imports `@sentry/node` so a
 * missing peer dep can't crash boot.
 *
 * The Edge runtime is NOT covered here: Edge functions in the app are
 * minimal (auth callback, middleware) and `@sentry/node` cannot run
 * there. If we add meaningful Edge logic later, add a separate
 * `sentry-edge.ts` and branch in `instrumentation.ts` on
 * `process.env.NEXT_RUNTIME`.
 */

let initialized = false;

export interface SentryServerOptions {
  dsn?: string;
  environment: string;
  release?: string;
  tracesSampleRate?: number;
}

/** Loose structural types: see sentry-browser.ts for rationale. */
interface SentryEventRequest {
  cookies?: string | unknown;
  headers?: Record<string, string> | unknown;
  data?: unknown;
}
interface SentryEvent {
  request?: SentryEventRequest;
  extra?: Record<string, unknown>;
}
interface SentryNodeModule {
  init(options: {
    dsn: string;
    environment: string;
    release?: string;
    tracesSampleRate?: number;
    sendDefaultPii?: boolean;
    beforeSend?: (event: SentryEvent) => SentryEvent | null;
  }): void;
  captureException(err: unknown, ctx?: { extra?: Record<string, unknown> }): string;
}

const SCRUB_KEYS = new Set([
  "password",
  "passwd",
  "pwd",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "secret",
  "api_key",
  "authorization",
  "cookie",
  "set-cookie",
]);

function scrub<T>(value: T, depth = 0): T {
  if (depth > 6 || value == null) return value;
  if (typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => scrub(v, depth + 1)) as unknown as T;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = SCRUB_KEYS.has(k.toLowerCase()) ? "[Scrubbed]" : scrub(v, depth + 1);
  }
  return out as T;
}

/**
 * Initialize Sentry for the Next.js Node runtime. Idempotent: safe to
 * call from multiple instrumentation hooks.
 */
export async function initServerSentry(opts: SentryServerOptions): Promise<boolean> {
  if (initialized) return true;
  if (!opts.dsn) return false;

  try {
    const Sentry = (await import(
      /* webpackIgnore: true */ "@sentry/node" as string
    )) as SentryNodeModule;
    Sentry.init({
      dsn: opts.dsn,
      environment: opts.environment,
      release: opts.release,
      tracesSampleRate: opts.tracesSampleRate ?? 0.1,
      sendDefaultPii: false,
      beforeSend(event: SentryEvent): SentryEvent {
        if (event.request) {
          if (event.request.cookies) event.request.cookies = "[Scrubbed]";
          if (event.request.headers) {
            const h = event.request.headers as Record<string, string>;
            for (const k of Object.keys(h)) {
              if (SCRUB_KEYS.has(k.toLowerCase())) h[k] = "[Scrubbed]";
            }
          }
          if (event.request.data) event.request.data = scrub(event.request.data);
        }
        if (event.extra) event.extra = scrub(event.extra);
        return event;
      },
    });
    initialized = true;
    return true;
  } catch (err) {

    console.warn("[observability] server Sentry init skipped:", (err as Error).message);
    return false;
  }
}

export function isServerSentryInitialized(): boolean {
  return initialized;
}

export async function captureServerException(
  err: unknown,
  context?: Record<string, unknown>,
): Promise<string | undefined> {
  if (!initialized) return undefined;
  try {
    const Sentry = (await import(
      /* webpackIgnore: true */ "@sentry/node" as string
    )) as SentryNodeModule;
    return Sentry.captureException(err, context ? { extra: scrub(context) } : undefined);
  } catch {
    return undefined;
  }
}
