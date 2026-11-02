/**
 * Browser-side Sentry stub for the marketing web app.
 *
 * The marketing site (`apps/web`) does NOT bundle the Sentry SDK by
 * design: it's a static landing page and shipping a 50KB telemetry
 * SDK to anonymous visitors hurts LCP/CLS and offers little value.
 *
 * This module exposes the same surface as the app shell's
 * `sentry-browser.ts` so callers can import either without a branch,
 * but every export is a no-op. If we later want telemetry on
 * marketing (e.g. to track 3D viewer crashes), swap this file's
 * implementation in lockstep with adding `@sentry/browser` to
 * `apps/web/package.json`.
 */

export interface SentryBrowserOptions {
  dsn?: string;
  environment: string;
  release?: string;
  tracesSampleRate?: number;
}

export async function initBrowserSentry(_opts: SentryBrowserOptions): Promise<boolean> {
  void _opts;
  return false;
}

export function isBrowserSentryInitialized(): boolean {
  return false;
}

export function captureBrowserException(
  _err: unknown,
  _context?: Record<string, unknown>,
): string | undefined {
  void _err;
  void _context;
  return undefined;
}

export async function setSentryUser(
  _user: { id?: string; email?: string } | null,
): Promise<void> {
  void _user;
  /* no-op */
}

export function setSentryTags(_tags: {
  org_id?: string;
  tier?: string;
  route?: string;
}): void {
  void _tags;
  /* no-op */
}
