/**
 * Exponential-backoff retry helper for transient client failures.
 *
 * Designed to wrap one-shot async calls (tRPC `fetch`, raw `fetch`,
 * Supabase client calls) where the caller wants automatic retries on
 * network errors and 5xxs without leaking the retry concern into every
 * call site.
 *
 *   const data = await retry(() => trpc.projects.list.fetch(), {
 *     attempts: 3,
 *     backoffMs: [200, 800, 2000],
 *     retryIf: (err) => isNetworkError(err),
 *   });
 *
 * - The total number of CALLS is `attempts` (not `attempts + 1`).
 * - Backoff happens BEFORE retries, never before the first call.
 * - If `backoffMs` is shorter than `attempts - 1`, we reuse the last
 *   delay (so `[200, 800, 2000]` with 5 attempts = [200, 800, 2000,
 *   2000, 2000]).
 * - The default `retryIf` retries on network errors and tRPC/HTTP 5xx
 *   responses. Mutations should pass a tighter `retryIf` to avoid
 *   accidental double-writes.
 */

export interface RetryOptions {
  /** Total number of attempts (includes the first try). Min 1. */
  attempts: number;
  /** Delays in ms applied BEFORE each retry. Last value is reused. */
  backoffMs: number[];
  /**
   * Predicate. Return true to retry, false to throw immediately.
   * Defaults to `defaultRetryIf` which catches network errors + 5xx.
   */
  retryIf?: (err: unknown, attempt: number) => boolean;
  /**
   * Optional jitter factor 0.0 - 1.0 applied to each delay.
   *   delay = base * (1 + random(-jitter, +jitter))
   * Default 0.2 (±20%) to avoid thundering herd on a recovering server.
   */
  jitter?: number;
  /** Optional AbortSignal: bails out of the loop early. */
  signal?: AbortSignal;
}

export class RetryAbortedError extends Error {
  constructor() {
    super("Retry aborted");
    this.name = "RetryAbortedError";
  }
}

/**
 * True when `err` looks like a transient network failure (connection
 * refused, DNS, fetch aborted by the browser, etc.). Exported so call
 * sites can build their own `retryIf` predicates without re-deriving
 * the regex.
 */
export function isNetworkError(err: unknown): boolean {
  if (!err) return false;
  if (typeof err === "object") {
    const e = err as { name?: string; message?: string; code?: string };
    if (e.name === "TypeError" && typeof e.message === "string") {
      return /Failed to fetch|NetworkError|fetch failed|Load failed/i.test(e.message);
    }
    if (e.code === "ECONNREFUSED" || e.code === "ENOTFOUND" || e.code === "ETIMEDOUT") {
      return true;
    }
    if (typeof e.message === "string" && /net::ERR|NetworkError/i.test(e.message)) {
      return true;
    }
  }
  return false;
}

/**
 * True when `err` is a tRPC/HTTP error with a 5xx status: i.e. the
 * server reached us but blew up. Safe to retry idempotent calls.
 */
export function is5xx(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as {
    data?: { httpStatus?: number };
    shape?: { data?: { httpStatus?: number } };
    status?: number;
  };
  const status =
    e.data?.httpStatus ?? e.shape?.data?.httpStatus ?? e.status ?? undefined;
  return typeof status === "number" && status >= 500 && status < 600;
}

/**
 * True when `err` looks like a 408 / 429 / 504: transient by HTTP
 * convention. We surface these alongside 5xx because they carry the
 * same "try again later" semantics.
 */
export function isTransientStatus(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as {
    data?: { httpStatus?: number; code?: string };
    shape?: { data?: { httpStatus?: number; code?: string } };
    status?: number;
  };
  const status = e.data?.httpStatus ?? e.shape?.data?.httpStatus ?? e.status;
  if (status === 408 || status === 429 || status === 504) return true;
  const code = e.data?.code ?? e.shape?.data?.code;
  return code === "TIMEOUT" || code === "CLIENT_CLOSED_REQUEST";
}

/** Default retry policy: network + transient HTTP failures only. */
export function defaultRetryIf(err: unknown): boolean {
  return isNetworkError(err) || is5xx(err) || isTransientStatus(err);
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new RetryAbortedError());
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new RetryAbortedError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function delayFor(opts: RetryOptions, attempt: number): number {
  const { backoffMs, jitter = 0.2 } = opts;
  if (backoffMs.length === 0) return 0;
  const base = backoffMs[Math.min(attempt, backoffMs.length - 1)] ?? 0;
  if (jitter <= 0) return base;
  const factor = 1 + (Math.random() * 2 - 1) * jitter;
  return Math.max(0, Math.round(base * factor));
}

/**
 * Retry `fn` up to `attempts` times with exponential-ish backoff.
 * Throws the last error if all attempts fail.
 */
export async function retry<T>(fn: () => Promise<T>, opts: RetryOptions): Promise<T> {
  if (opts.attempts < 1) throw new Error("retry: attempts must be >= 1");
  const predicate = opts.retryIf ?? defaultRetryIf;

  let lastErr: unknown;
  for (let attempt = 0; attempt < opts.attempts; attempt++) {
    if (opts.signal?.aborted) throw new RetryAbortedError();
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const isLast = attempt === opts.attempts - 1;
      if (isLast || !predicate(err, attempt)) throw err;
      const wait = delayFor(opts, attempt);
      if (wait > 0) await sleep(wait, opts.signal);
    }
  }
  // Unreachable: the loop always returns or throws.
  throw lastErr;
}
