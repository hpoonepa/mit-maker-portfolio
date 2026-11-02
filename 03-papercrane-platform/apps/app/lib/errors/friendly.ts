/**
 * Translate raw tRPC / fetch errors into user-friendly copy and a
 * suggested next action. Centralised so toasts and inline banners stay
 * consistent.
 *
 * This is now a thin compatibility wrapper over `trpc-error-map.ts`
 * (which is the canonical mapper, keyed off `err.data.code`). Existing
 * call sites that import `friendlyTrpcError` keep working; new call
 * sites should prefer `mapTrpcError` for the richer, action-aware
 * result.
 */

import { mapTrpcError, type MapErrorContext } from "./trpc-error-map";

export type FriendlyAction = "retry" | "login" | "support" | "none";

export interface FriendlyError {
  message: string;
  action: FriendlyAction;
  /** HTTP status when known. */
  status?: number;
  /** Optional support reference id (5xx). */
  errorId?: string;
  /** Short toast title. */
  title?: string;
}

/**
 * Map a tRPC mutation/query error to user-readable text. Falls back to
 * the raw message when nothing matches.
 *
 * Pass `ctx.resource` (e.g. "project", "API key") to get noun-aware
 * NOT_FOUND / CONFLICT copy.
 */
export function friendlyTrpcError(
  err: unknown,
  ctx: MapErrorContext = {},
): FriendlyError {
  const m = mapTrpcError(err, ctx);
  let action: FriendlyAction;
  switch (m.action.kind) {
    case "retry":
      action = "retry";
      break;
    case "login":
      action = "login";
      break;
    case "support":
      action = "support";
      break;
    default:
      action = "none";
  }
  return {
    title: m.title,
    message: m.message,
    action,
    status: m.status,
    errorId: m.errorId,
  };
}

/** Build the next-aware login redirect URL for a 401. */
export function loginUrlWithNext(currentPath: string): string {
  const safe = currentPath.startsWith("/") ? currentPath : `/${currentPath}`;
  return `/login?next=${encodeURIComponent(safe)}`;
}

export { mapTrpcError } from "./trpc-error-map";
export type { MappedError, MapErrorContext, ErrorAction, TrpcCode } from "./trpc-error-map";
