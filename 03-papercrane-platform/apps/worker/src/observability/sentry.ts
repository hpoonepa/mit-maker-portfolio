/**
 * Worker-side Sentry initialization.
 *
 * Same shape as `apps/api/src/observability/sentry.ts` — gated on `SENTRY_DSN`,
 * dynamic-imported so a missing peer dep can't crash boot. Worker exceptions
 * are typically captured from BullMQ's `failed` event handler in `index.ts`
 * and from the `unhandledRejection` / `uncaughtException` handlers in
 * `server.ts`.
 */
import type { InitSentryOptions } from '@papercrane/observability';

let initialized = false;

/**
 * Initialize Sentry for the worker. Returns true if events will actually be
 * sent. Safe to call multiple times — idempotent on success.
 */
export async function initWorkerSentry(opts: InitSentryOptions): Promise<boolean> {
  if (initialized) return true;
  if (!opts.dsn) return false;

  try {
    const obs = await import('@papercrane/observability');
    const ok = obs.initSentry(opts);
    initialized = ok;
    return ok;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[observability] Sentry init skipped:', (err as Error).message);
    return false;
  }
}

/** Whether Sentry was successfully initialized in this process. */
export function isWorkerSentryInitialized(): boolean {
  return initialized;
}

/**
 * Capture an exception with optional context. No-op when Sentry isn't
 * initialized. Use this from BullMQ failure handlers and process-level
 * uncaught error handlers.
 */
export async function captureWorkerException(
  err: unknown,
  context?: Record<string, unknown>,
): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import('@papercrane/observability');
    obs.captureException(err, context);
  } catch {
    /* swallow */
  }
}

/**
 * Tag the current Sentry scope with a job id / request id. Useful from worker
 * job processors so a captured exception is correlated with the failing job.
 */
export async function tagJobId(jobId: string): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import('@papercrane/observability');
    obs.Sentry.getCurrentScope().setTag('job_id', jobId);
  } catch {
    /* swallow */
  }
}

/**
 * Tag the worker scope with org/tier/job metadata. Call from the BullMQ
 * `processor` once the job's auth context is resolved so any exception
 * captured during processing carries the same dimensions as the API.
 */
export async function tagWorkerContext(tags: {
  org_id?: string;
  tier?: string;
  queue?: string;
  job_id?: string;
  user_id?: string;
}): Promise<void> {
  if (!initialized) return;
  try {
    const obs = await import('@papercrane/observability');
    const scope = obs.Sentry.getCurrentScope();
    for (const [k, v] of Object.entries(tags)) {
      if (v !== undefined && k !== 'user_id') scope.setTag(k, String(v));
    }
    if (tags.user_id) {
      scope.setUser({ id: tags.user_id });
    }
  } catch {
    /* swallow */
  }
}

/**
 * Install process-level handlers that flush Sentry, log to stderr, and
 * exit cleanly so the process manager (Fly.io) restarts the worker.
 *
 *   - `unhandledRejection` and `uncaughtException` → capture + drain +
 *     exit(1).
 *   - `SIGTERM` / `SIGINT` → graceful shutdown via the supplied
 *     `drainInflight` callback.
 *
 * Returns a teardown fn (mostly useful from tests).
 */
export function installCrashHandlers(opts: {
  drainInflight: () => Promise<void>;
  drainTimeoutMs?: number;
}): () => void {
  const drainTimeoutMs = opts.drainTimeoutMs ?? 30_000;
  let shuttingDown = false;

  const finish = async (code: number, reason: string, err?: unknown): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    // eslint-disable-next-line no-console
    console.error(`[worker] shutting down (${reason})`, err ?? '');
    if (err) await captureWorkerException(err, { source: reason });

    const drainP = opts.drainInflight().catch((e) => {
      // eslint-disable-next-line no-console
      console.error('[worker] drain failed', e);
    });
    const timeoutP = new Promise<void>((resolve) => setTimeout(resolve, drainTimeoutMs));
    await Promise.race([drainP, timeoutP]);

    // Best-effort flush so events make it out before exit.
    try {
      const obs = await import('@papercrane/observability');
      await obs.Sentry.close(2_000);
    } catch {
      /* swallow */
    }
    process.exit(code);
  };

  const onUnhandled = (err: unknown): void => {
    void finish(1, 'unhandledRejection', err);
  };
  const onUncaught = (err: unknown): void => {
    void finish(1, 'uncaughtException', err);
  };
  const onSigterm = (): void => {
    void finish(0, 'SIGTERM');
  };
  const onSigint = (): void => {
    void finish(0, 'SIGINT');
  };

  process.on('unhandledRejection', onUnhandled);
  process.on('uncaughtException', onUncaught);
  process.on('SIGTERM', onSigterm);
  process.on('SIGINT', onSigint);

  return () => {
    process.off('unhandledRejection', onUnhandled);
    process.off('uncaughtException', onUncaught);
    process.off('SIGTERM', onSigterm);
    process.off('SIGINT', onSigint);
  };
}
