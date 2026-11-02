"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";
import { captureBrowserException } from "@/lib/observability/sentry-browser";

/**
 * Sentry-aware route error boundary.
 *
 * Distinct from `ErrorBoundary` (which is the generic component used
 * inside subtrees): this one is tuned for route-segment use, surfaces a
 * shareable error ID (`PCN-YYYY-MM-DD-xxxxx`), and forwards every
 * caught error to Sentry with `route` + `digest` tags so the logged
 * event is correlated with the support reference the user can read out.
 *
 * Use in a Client Component:
 *
 *   <RouteErrorBoundary route="projects.detail">
 *     <ProjectDetail …/>
 *   </RouteErrorBoundary>
 *
 * For Next.js route-segment errors, prefer the file-based `error.tsx` -
 * Next handles the boundary plumbing and we only render the UI. This
 * class form exists for client subtrees that want isolation without
 * splitting into a route segment.
 */

export interface RouteErrorBoundaryProps {
  children: ReactNode;
  /** Route slug used as a Sentry tag and surfaced in the support ID. */
  route?: string;
  /** Override the fallback UI. */
  fallback?: (args: { error: Error; errorId: string; retry: () => void }) => ReactNode;
  /** Additional onError callback (telemetry beyond Sentry). */
  onError?: (error: Error, info: ErrorInfo, errorId: string) => void;
}

interface RouteErrorBoundaryState {
  error: Error | null;
  errorId: string | null;
}

export class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  state: RouteErrorBoundaryState = { error: null, errorId: null };

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error, errorId: buildErrorId() };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const errorId = this.state.errorId ?? buildErrorId();
    if (this.state.errorId !== errorId) {
      this.setState({ errorId });
    }

    // Forward to Sentry with route context so the event matches the
    // support reference the user sees on screen.
    try {
      captureBrowserException(error, {
        error_id: errorId,
        route: this.props.route,
        component_stack: info.componentStack,
      });
    } catch {
      /* swallow: telemetry must not crash the boundary */
    }

    this.props.onError?.(error, info, errorId);

    console.error("[RouteErrorBoundary]", { errorId, error, info });
  }

  retry = (): void => {
    this.setState({ error: null, errorId: null });
  };

  render(): ReactNode {
    const { error, errorId } = this.state;
    if (!error || !errorId) return this.props.children;

    if (this.props.fallback) {
      return this.props.fallback({ error, errorId, retry: this.retry });
    }

    return <DefaultRouteFallback error={error} errorId={errorId} onRetry={this.retry} />;
  }
}

/**
 * Build a human-friendly support reference: `PCN-YYYY-MM-DD-xxxxx`.
 * Combines the date (so an oncall engineer can scope log search) with
 * a 5-char base36 hash (random-enough for unique-per-render). Stable
 * format means support agents can paste it straight into our logs UI.
 */
export function buildErrorId(now: Date = new Date()): string {
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, "0");
  const d = String(now.getUTCDate()).padStart(2, "0");
  const rand = Math.floor(Math.random() * 36 ** 5)
    .toString(36)
    .padStart(5, "0")
    .slice(-5);
  return `PCN-${y}-${m}-${d}-${rand}`;
}

function DefaultRouteFallback({
  error,
  errorId,
  onRetry,
}: {
  error: Error;
  errorId: string;
  onRetry: () => void;
}) {
  return (
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
      <button
        type="button"
        onClick={onRetry}
        className="mt-6 inline-flex items-center gap-2 btn-primary"
      >
        <RefreshCcw className="w-4 h-4" />
        Retry
      </button>
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
