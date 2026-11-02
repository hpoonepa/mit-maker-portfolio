/**
 * Browser-side observability: Sentry placeholder.
 *
 * The Sentry browser SDK is not currently installed (kept out of the bundle
 * for size). This module exposes the same API surface other modules import,
 * but every function is a no-op until the SDK is wired up.
 *
 * To enable Sentry later:
 *   1. `pnpm --filter @papercrane/app add @sentry/browser`
 *   2. Replace the body of `initBrowserSentry` to dynamically import the SDK
 *   3. Set NEXT_PUBLIC_SENTRY_DSN in env
 */

export interface Scope {
  setTag(key: string, value: string | number | boolean): void;
  setUser(user: { id?: string; email?: string } | null): void;
  setExtras(extras: Record<string, unknown>): void;
}

export interface SentryBrowserOptions {
  dsn?: string;
  environment: string;
  release?: string;
  tracesSampleRate?: number;
}

export async function initBrowserSentry(
  _opts: SentryBrowserOptions,
): Promise<boolean> {
  return false;
}

export function isBrowserSentryInitialized(): boolean {
  return false;
}

export function captureBrowserException(
  _err: unknown,
  _context?: Record<string, unknown>,
): string | undefined {
  return undefined;
}

export async function setSentryUser(
  _user: { id?: string; email?: string } | null,
): Promise<void> {
  // no-op
}

export function setSentryTags(_tags: {
  org_id?: string;
  tier?: string;
  route?: string;
}): void {
  // no-op
}
