/**
 * Dev-only tRPC link that logs every client error to a structured
 * console group AND posts a redacted summary to `/api/dev/log-error`
 * (which appends to `.agent-logs/client-errors.json` for offline
 * debugging). Production builds short-circuit to a no-op so the link
 * is safe to leave in the chain.
 *
 * Implemented on top of the official `loggerLink` so we don't have to
 * import `@trpc/server/observable` directly (the app only depends on
 * `@trpc/client` / `@trpc/react-query`).
 */

import { loggerLink, TRPCClientError } from "@trpc/client";
import { mapTrpcError } from "../errors/trpc-error-map";

const isDev =
  typeof process !== "undefined" && process.env.NODE_ENV !== "production";

interface LoggedError {
  ts: string;
  path: string;
  type: string;
  code?: string;
  status?: number;
  message: string;
  mappedTitle: string;
  mappedMessage: string;
  errorId?: string;
}

function postToDevLog(payload: LoggedError): void {
  // Best-effort fire-and-forget. Failures here must not surface to the user.
  try {
    void fetch("/api/dev/log-error", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* no-op */
  }
}

/**
 * Build the dev-only error logger link. Wraps `@trpc/client`'s
 * `loggerLink` with a custom logger that fires only for `down` results
 * carrying a `TRPCClientError`.
 */
export function errorLoggerLink() {
  return loggerLink({
    enabled: (opts) =>
      isDev && opts.direction === "down" && opts.result instanceof TRPCClientError,
    logger: (opts) => {
      if (opts.direction !== "down") return;
      const { result } = opts;
      if (!(result instanceof TRPCClientError)) return;

      const mapped = mapTrpcError(result);
      const payload: LoggedError = {
        ts: new Date().toISOString(),
        path: opts.path,
        type: opts.type,
        code: mapped.code,
        status: mapped.status,
        message: result.message ?? "",
        mappedTitle: mapped.title,
        mappedMessage: mapped.message,
        errorId: mapped.errorId,
      };

      console.groupCollapsed(
        `[trpc] ${opts.type} ${opts.path} → ${mapped.code ?? mapped.status ?? "ERR"}`,
      );

      console.error(result);

      console.info("mapped:", mapped);

      console.groupEnd();
      postToDevLog(payload);
    },
  });
}
