/**
 * Specific, actionable error UX for tRPC failures.
 *
 * Reads `err.data.code` (the standard tRPC `TRPC_ERROR_CODE_KEY`) and
 * returns a UI-ready message tuned to the failure mode. Falls back to
 * the raw `err.message` if the code is unknown so server-authored
 * BAD_REQUEST messages reach the user verbatim.
 *
 * NOTE: kept dependency-free so it can be imported by both the toast
 * call sites (Client Components) and the global tRPC link without
 * dragging React into the link layer.
 */

export type TrpcCode =
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "BAD_REQUEST"
  | "CONFLICT"
  | "TOO_MANY_REQUESTS"
  | "INTERNAL_SERVER_ERROR"
  | "TIMEOUT"
  | "PRECONDITION_FAILED"
  | "PAYLOAD_TOO_LARGE"
  | "METHOD_NOT_SUPPORTED"
  | "UNSUPPORTED_MEDIA_TYPE"
  | "UNPROCESSABLE_CONTENT"
  | "CLIENT_CLOSED_REQUEST"
  | "PARSE_ERROR";

export type ErrorAction =
  | { kind: "none" }
  | { kind: "retry" }
  | { kind: "login"; redirectAfterMs: number; nextPath?: string }
  | { kind: "switch_org" }
  | { kind: "support"; errorId: string };

export interface MappedError {
  /** Short toast title: what happened, in 2-4 words. */
  title: string;
  /** Body copy with concrete next step. */
  message: string;
  /** Optional follow-up the UI can hook into (redirect, switch org, etc.). */
  action: ErrorAction;
  /** tRPC code if we recognised one. */
  code?: TrpcCode;
  /** HTTP status when known. */
  status?: number;
  /** Stable id for linking to /app/error/[id] when we file a support trace. */
  errorId?: string;
}

/** Context for shaping resource-specific copy ("project", "API key", etc.). */
export interface MapErrorContext {
  /** Resource noun used in NOT_FOUND / CONFLICT copy ("project", "API key"). */
  resource?: string;
  /** Field that conflicted, used in CONFLICT copy ("name", "slug"). */
  conflictField?: string;
  /** Where to send the user after a UNAUTHORIZED redirect. */
  nextPath?: string;
}

/** Loose shape we expect from a tRPC client error (no hard dep on tRPC types). */
interface RawErrorLike {
  message?: string;
  name?: string;
  data?: {
    code?: string;
    httpStatus?: number;
  };
  shape?: {
    data?: { code?: string; httpStatus?: number };
    message?: string;
  };
}

const NETWORK_RE = /(NetworkError|Failed to fetch|fetch failed|ECONNREFUSED|ENOTFOUND|net::ERR)/i;
const HTML_RE = /(Unexpected token '?<'?|<!DOCTYPE|<html)/i;

let errorIdCounter = 0;
function nextErrorId(): string {
  errorIdCounter += 1;
  // 8-char base36 timestamp + counter: short enough to read out for support
  // and stable enough to copy/paste into a ticket without a UUID lib.
  return `err_${Date.now().toString(36)}${errorIdCounter.toString(36).padStart(2, "0")}`;
}

/**
 * Map a raw tRPC / fetch error to UI-ready copy.
 */
export function mapTrpcError(
  err: unknown,
  ctx: MapErrorContext = {},
): MappedError {
  const resource = ctx.resource ?? "resource";
  const conflictField = ctx.conflictField ?? "name";

  if (!err) {
    return {
      title: "Something went wrong",
      message: "Unknown error. Try again.",
      action: { kind: "none" },
    };
  }

  const e = err as RawErrorLike;
  const raw =
    typeof e.message === "string" && e.message.length > 0
      ? e.message
      : "Something went wrong.";
  const code = (e.data?.code ?? e.shape?.data?.code) as TrpcCode | undefined;
  const status = e.data?.httpStatus ?? e.shape?.data?.httpStatus;

  // ---- Network failures (no response from server) ------------------------
  if (NETWORK_RE.test(raw) || e.name === "TypeError") {
    return {
      title: "Connection lost",
      message:
        "Can't reach the server. Check your connection and try again.",
      action: { kind: "retry" },
      status,
    };
  }

  // ---- Server returned HTML instead of JSON (5xx page leaked through) ----
  if (HTML_RE.test(raw)) {
    const errorId = nextErrorId();
    return {
      title: "Server error",
      message: `Something went wrong on our end. We've been notified. Reference: ${errorId}`,
      action: { kind: "support", errorId },
      code: "INTERNAL_SERVER_ERROR",
      status: status ?? 500,
      errorId,
    };
  }

  // ---- Known tRPC codes ---------------------------------------------------
  switch (code) {
    case "UNAUTHORIZED":
      return {
        title: "Session expired",
        message: "Please sign in again. Your session may have expired.",
        action: {
          kind: "login",
          redirectAfterMs: 2000,
          nextPath: ctx.nextPath,
        },
        code,
        status: status ?? 401,
      };

    case "FORBIDDEN":
      return {
        title: "Not allowed",
        message:
          "You don't have permission to do that. Try switching to a different org.",
        action: { kind: "switch_org" },
        code,
        status: status ?? 403,
      };

    case "NOT_FOUND":
      return {
        title: "Not found",
        message: `We couldn't find that ${resource}. It may have been deleted.`,
        action: { kind: "none" },
        code,
        status: status ?? 404,
      };

    case "BAD_REQUEST":
    case "UNPROCESSABLE_CONTENT":
    case "PARSE_ERROR":
      // Server-authored validation messages are user-facing: pass through.
      return {
        title: "Check the form",
        message: raw,
        action: { kind: "none" },
        code,
        status: status ?? 400,
      };

    case "CONFLICT":
      return {
        title: "Already exists",
        message: `A ${resource} with that ${conflictField} already exists. Try a different ${conflictField}.`,
        action: { kind: "none" },
        code,
        status: status ?? 409,
      };

    case "TOO_MANY_REQUESTS":
      return {
        title: "Slow down",
        message:
          "Whoa, slow down. You're hitting our rate limit. Try again in a moment.",
        action: { kind: "retry" },
        code,
        status: status ?? 429,
      };

    case "TIMEOUT":
    case "CLIENT_CLOSED_REQUEST":
      return {
        title: "Request timed out",
        message: "The request took too long. Try again.",
        action: { kind: "retry" },
        code,
        status,
      };

    case "PAYLOAD_TOO_LARGE":
      return {
        title: "Too large",
        message: "That payload is too big. Try a smaller upload.",
        action: { kind: "none" },
        code,
        status: status ?? 413,
      };

    case "INTERNAL_SERVER_ERROR": {
      const errorId = nextErrorId();
      return {
        title: "Server error",
        message: `Something went wrong on our end. We've been notified. Reference: ${errorId}`,
        action: { kind: "support", errorId },
        code,
        status: status ?? 500,
        errorId,
      };
    }
  }

  // ---- Status-only fallback (no code attached) ---------------------------
  if (status && status >= 500) {
    const errorId = nextErrorId();
    return {
      title: "Server error",
      message: `Something went wrong on our end. We've been notified. Reference: ${errorId}`,
      action: { kind: "support", errorId },
      status,
      errorId,
    };
  }

  // ---- Last resort: pass the raw message through -------------------------
  return {
    title: "Something went wrong",
    message: raw,
    action: { kind: "none" },
    status,
  };
}

/** Build the next-aware login redirect URL for a 401. */
export function loginUrlWithNext(currentPath: string): string {
  const safe = currentPath.startsWith("/") ? currentPath : `/${currentPath}`;
  return `/login?next=${encodeURIComponent(safe)}`;
}
