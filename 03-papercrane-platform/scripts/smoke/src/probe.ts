/**
 * HTTP probe helper. Uses Node's built-in `fetch` (Node >=20) — no HTTP deps.
 *
 * Responsibilities:
 *   - issue a single request with a configurable timeout (AbortController)
 *   - retry on network/timeout errors up to `retries` times with backoff
 *   - assert status + body + content-type against an ExpectedOutcome
 *   - never throw for a bad assertion — return a structured ProbeResult so the
 *     runner can aggregate and render junit-xml
 */

import type { ExpectedOutcome, RouteSpec } from './routes.js';

export type ProbeResult = {
  route: RouteSpec;
  url: string;
  /** True if every assertion passed. */
  passed: boolean;
  /** HTTP status of the final attempt, or undefined if all attempts errored. */
  status?: number;
  /** Content-type header of the final attempt. */
  contentType?: string;
  /** Total number of attempts (1 + retries actually used). */
  attempts: number;
  /** Wall-clock duration across all attempts, ms. */
  durationMs: number;
  /** Human-readable failure reason when `passed` is false. */
  failureReason?: string;
  /** Truncated body snippet for diagnostics (first 500 chars). */
  bodySnippet?: string;
};

export type ProbeOptions = {
  /** Total attempts = 1 + retries. Default: 3 retries. */
  retries?: number;
  /** Per-attempt timeout in ms. Default: 10_000. */
  timeoutMs?: number;
  /** Base backoff in ms, doubled each retry. Default: 250. */
  backoffMs?: number;
  /** Override fetch — used by tests to simulate responses. */
  fetchImpl?: typeof fetch;
  /** Override sleep — used by tests to run without real delays. */
  sleepImpl?: (ms: number) => Promise<void>;
};

export async function probeRoute(
  baseUrl: string,
  route: RouteSpec,
  opts: ProbeOptions = {}
): Promise<ProbeResult> {
  const retries = opts.retries ?? 3;
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const backoffMs = opts.backoffMs ?? 250;
  const doFetch = opts.fetchImpl ?? fetch;
  const doSleep = opts.sleepImpl ?? defaultSleep;

  const url = joinUrl(baseUrl, route.path);
  const started = Date.now();

  let lastError: unknown;
  let attempts = 0;

  for (let attempt = 0; attempt <= retries; attempt++) {
    attempts = attempt + 1;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await doFetch(url, {
        method: route.method,
        // Include a header so it's obvious in access logs where hits came from.
        headers: { 'user-agent': 'papercrane-smoke/0.1' },
        redirect: 'manual',
        signal: controller.signal,
      });
      clearTimeout(timer);

      const contentType = res.headers.get('content-type') ?? undefined;
      // Only read the body when we actually need it — saves time on redirects.
      const needsBody = Boolean(
        route.expected.bodyContains?.length && isOk(res.status)
      );
      const bodyText = needsBody ? await res.text() : '';
      const bodySnippet = bodyText ? bodyText.slice(0, 500) : undefined;

      const failureReason = assertExpected(
        route.expected,
        res.status,
        contentType,
        bodyText
      );

      if (!failureReason) {
        return {
          route,
          url,
          passed: true,
          status: res.status,
          contentType,
          attempts,
          durationMs: Date.now() - started,
          bodySnippet,
        };
      }

      // Assertion failure — no point retrying, the server answered cleanly.
      return {
        route,
        url,
        passed: false,
        status: res.status,
        contentType,
        attempts,
        durationMs: Date.now() - started,
        failureReason,
        bodySnippet,
      };
    } catch (err) {
      clearTimeout(timer);
      lastError = err;
      if (attempt < retries) {
        await doSleep(backoffMs * 2 ** attempt);
        continue;
      }
    }
  }

  return {
    route,
    url,
    passed: false,
    attempts,
    durationMs: Date.now() - started,
    failureReason: `network error after ${attempts} attempts: ${stringifyError(lastError)}`,
  };
}

/**
 * Pure assertion helper — exposed for unit tests. Returns undefined on pass,
 * or a human-readable failure reason on failure.
 */
export function assertExpected(
  expected: ExpectedOutcome,
  status: number,
  contentType: string | undefined,
  body: string
): string | undefined {
  if (!expected.statuses.includes(status)) {
    return `status ${status} not in [${expected.statuses.join(', ')}]`;
  }
  if (expected.contentTypePrefix) {
    const ct = (contentType ?? '').toLowerCase();
    if (!ct.startsWith(expected.contentTypePrefix.toLowerCase())) {
      return `content-type "${contentType ?? '(missing)'}" does not start with "${expected.contentTypePrefix}"`;
    }
  }
  if (expected.bodyContains?.length && isOk(status)) {
    const haystack = body.toLowerCase();
    for (const needle of expected.bodyContains) {
      if (!haystack.includes(needle.toLowerCase())) {
        return `body missing required substring "${needle}"`;
      }
    }
  }
  return undefined;
}

export function joinUrl(base: string, path: string): string {
  const trimmedBase = base.replace(/\/+$/, '');
  const prefixedPath = path.startsWith('/') ? path : `/${path}`;
  return `${trimmedBase}${prefixedPath}`;
}

function isOk(status: number): boolean {
  return status >= 200 && status < 300;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stringifyError(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

/**
 * Wait for a port to accept connections by polling a health URL. Uses the same
 * `fetch` impl as probe so tests can stub it.
 */
export async function waitForReady(
  baseUrl: string,
  opts: {
    maxWaitMs?: number;
    intervalMs?: number;
    fetchImpl?: typeof fetch;
    sleepImpl?: (ms: number) => Promise<void>;
    onAttempt?: (attempt: number) => void;
  } = {}
): Promise<void> {
  const maxWaitMs = opts.maxWaitMs ?? 90_000;
  const intervalMs = opts.intervalMs ?? 1_000;
  const doFetch = opts.fetchImpl ?? fetch;
  const doSleep = opts.sleepImpl ?? defaultSleep;

  const deadline = Date.now() + maxWaitMs;
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt++;
    opts.onAttempt?.(attempt);
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), intervalMs * 2);
      const res = await doFetch(joinUrl(baseUrl, '/'), {
        method: 'HEAD',
        signal: controller.signal,
      });
      clearTimeout(timer);
      // Any HTTP answer counts as "server is alive" — even a 500 means the
      // Node process is serving requests, which is all readiness requires.
      if (res.status > 0) return;
    } catch {
      // swallow — keep polling
    }
    await doSleep(intervalMs);
  }

  throw new Error(
    `server not ready at ${baseUrl} after ${maxWaitMs}ms (${attempt} attempts)`
  );
}
