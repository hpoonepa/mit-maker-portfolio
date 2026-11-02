"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional override for the fallback UI. */
  fallback?: (error: Error, retry: () => void) => ReactNode;
  /** Called when an error is caught. Useful for telemetry. */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Page-level error boundary with a "Something went wrong + Retry" UI.
 * Wrap a route subtree (server-rendered errors should use Next's
 * error.tsx instead).
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info);

    console.error("[ErrorBoundary]", error, info);
  }

  retry = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) {
      return this.props.fallback(error, this.retry);
    }

    return <DefaultErrorFallback error={error} onRetry={this.retry} />;
  }
}

function DefaultErrorFallback({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  const message = friendlyMessage(error);
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
        {message}
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
