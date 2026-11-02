/**
 * API-side Sentry initialization.
 *
 * Thin wrapper over `@papercrane/observability`'s shared init. Gated on
 * `SENTRY_DSN` — degrades to a no-op when absent so local dev never ships
 * events. The shared package depends on `@sentry/node` directly, but this
 * module loads it via dynamic import so a missing peer dep can't crash the
 * process at import time.
 */
import type { InitSentryOptions } from "@papercrane/observability";

let initialized = false;

/**
 * Initialize Sentry for the API. Returns true if events will actually be sent.
 * Safe to call multiple times — the second call is a no-op.
 *
 * Use a dynamic import so that if `@papercrane/observability` ever drops the
 * `@sentry/node` dep (or a future build splits it out), the API still boots.
 */
export async function initApiSentry(opts: InitSentryOptions): Promise<boolean> {
  if (initialized) return true;
  if (!opts.dsn) return false;

  try {
    const obs = await import("@papercrane/observability");
    const ok = obs.initSentry(opts);
    initialized = ok;
    return ok;
  } catch (err) {
    // SDK not installed or failed to load — degrade silently.
    // Use console because the logger may not be wired yet at this point.
    // eslint-disable-next-line no-console
    console.warn("[observability] Sentry init skipped:", (err as Error).message);
    return false;
  }
}

/** Whether `initApiSentry` succeeded with a DSN in this process. */
export function isApiSentryInitialized(): boolean {
  return initialized;
}

/**
 * Capture an exception without depending on Sentry being available. Forwards
 * to the shared package; no-ops if Sentry was never initialized.
 */
export async function captureApiException(
  err: unknown,
  context?: Record<string, unknown>,
): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import("@papercrane/observability");
    obs.captureException(err, context);
  } catch {
    /* swallow — best-effort */
  }
}

/**
 * Tag the current Sentry scope with a request id so any exception captured
 * during the request is correlated. No-op when Sentry is not initialized.
 */
export async function tagRequestId(requestId: string): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import("@papercrane/observability");
    obs.Sentry.getCurrentScope().setTag("request_id", requestId);
  } catch {
    /* swallow */
  }
}

/**
 * Tag the current scope with org/tier/route metadata. Use from tRPC
 * middleware once the auth context is resolved, so server-side captures
 * carry the same dimensions as client-side ones.
 */
export async function tagApiContext(tags: {
  org_id?: string;
  tier?: string;
  route?: string;
  user_id?: string;
}): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import("@papercrane/observability");
    const scope = obs.Sentry.getCurrentScope();
    for (const [k, v] of Object.entries(tags)) {
      if (v !== undefined && k !== "user_id") scope.setTag(k, String(v));
    }
    if (tags.user_id) {
      scope.setUser({ id: tags.user_id });
    }
  } catch {
    /* swallow */
  }
}
