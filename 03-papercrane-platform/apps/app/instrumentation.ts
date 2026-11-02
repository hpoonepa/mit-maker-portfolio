/**
 * Next.js instrumentation hook: runs once per server process before any
 * request is served. Used here to bootstrap Sentry on the Node runtime.
 *
 * Docs: https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation
 *
 * The Edge runtime path is intentionally a no-op: `@sentry/node` cannot
 * run on Edge, and our Edge surface (middleware) is small enough that
 * server-side capture from the Node runtime suffices.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const dsn = process.env.SENTRY_DSN;
  if (!dsn) return;

  // Dynamic import keeps `@sentry/node` out of the Edge bundle.
  const { initServerSentry } = await import("./lib/observability/sentry-server");
  await initServerSentry({
    dsn,
    environment: process.env.NEXT_PUBLIC_VERCEL_ENV ?? process.env.NODE_ENV ?? "development",
    release: process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA,
    tracesSampleRate: 0.1,
  });
}

/**
 * Next 15+ request error hook: fires for any error thrown during a
 * server render or Server Action. We forward to Sentry with the route
 * + digest so they correlate with the friendly digest the user sees.
 */
export async function onRequestError(
  err: unknown,
  request: { path: string; method: string; headers: Record<string, string | string[] | undefined> },
  context: { routerKind: string; routePath: string; routeType: string },
): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (!process.env.SENTRY_DSN) return;

  try {
    const { captureServerException } = await import("./lib/observability/sentry-server");
    await captureServerException(err, {
      route: context.routePath,
      route_kind: context.routerKind,
      route_type: context.routeType,
      method: request.method,
      path: request.path,
    });
  } catch {
    /* swallow: instrumentation must never throw */
  }
}
