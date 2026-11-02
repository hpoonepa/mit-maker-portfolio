"use client";

import { useEffect, useMemo } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";
import { captureBrowserException } from "@/lib/observability/sentry-browser";
import { buildErrorId } from "@/components/error/RouteErrorBoundary";

/**
 * Dashboard route error boundary. Next 16 invokes this when a server or
 * client error escapes a page in the (dashboard) segment.
 *
 * Hardened (Wave 15):
 *   - Generates a `PCN-YYYY-MM-DD-xxxxx` reference so users can quote a
 *     stable id to support, separate from Next's internal `digest`.
 *   - Forwards the error to Sentry with `route_segment: dashboard` and
 *     both ids tagged, so server-side traces and the user-facing
 *     reference correlate one-to-one.
 *
 * Keep this component small: it must render even if half the runtime
 * is misbehaving. Visual style matches `<RouteErrorBoundary>` so
 * client-side errors look consistent regardless of where they bubble up.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Stable id for this render: recomputed only when the underlying
  // error reference changes, so a parent re-render doesn't flicker the
  // support reference visible on screen.
  const errorId = useMemo(() => buildErrorId(), [error]);

  useEffect(() => {

    console.error("[dashboard/error]", { errorId, digest: error.digest, error });
    try {
      captureBrowserException(error, {
        error_id: errorId,
        route_segment: "dashboard",
        digest: error.digest,
      });
    } catch {
      /* never throw from the boundary */
    }
  }, [error, errorId]);

  return (
    <div className="mx-auto max-w-xl px-4 py-16">
      <div
        role="alert"
        className="rounded-lg border border-crane/40 bg-crane-glow/40 px-8 py-12 text-center"
      >
        <div className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-lg border border-crane/40 bg-paper text-crane-deep">
          <AlertTriangle className="w-5 h-5" />
        </div>
        <h2 className="mt-5 font-display text-[24px] text-ink">
          Something went wrong
        </h2>
        <p className="mt-2 mx-auto max-w-md font-sans text-[14px] text-graphite">
          {friendlyMessage(error)}
        </p>
        <p className="mt-3 font-mono text-[11px] text-graphite-soft">
          Reference: <span className="text-ink">{errorId}</span>
        </p>
        {error.digest && (
          <p className="mt-1 font-mono text-[11px] text-graphite-soft">
            Server digest: <span className="text-ink">{error.digest}</span>
          </p>
        )}
        <button
          type="button"
          onClick={reset}
          className="mt-6 inline-flex items-center gap-2 btn-primary"
        >
          <RefreshCcw className="w-4 h-4" />
          Try again
        </button>
        <p className="mt-4 font-sans text-[12px] text-graphite-soft">
          If this keeps happening, email{" "}
          <a href={`mailto:support@papercrane.bio?subject=Error%20${errorId}`} className="text-crane-deep underline">
            support@papercrane.bio
          </a>{" "}
          with the reference above.
        </p>
      </div>
    </div>
  );
}

function friendlyMessage(error: Error): string {
  const raw = error.message || "An unexpected error occurred.";
  if (/Unexpected token '?<'?/.test(raw)) {
    return "Backend unreachable. Try again or contact support.";
  }
  if (/NetworkError|Failed to fetch/i.test(raw)) {
    return "Network error. Check your connection and retry.";
  }
  return raw;
}
