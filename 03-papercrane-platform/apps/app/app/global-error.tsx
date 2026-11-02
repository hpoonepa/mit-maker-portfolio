"use client";

import { useEffect, useMemo } from "react";
import { captureBrowserException } from "@/lib/observability/sentry-browser";
import { buildErrorId } from "@/components/error/RouteErrorBoundary";

/**
 * Next.js global error boundary: last line of defence.
 *
 * Fires when the root layout itself throws (e.g. providers crash, the
 * tRPC client fails to initialise, theme provider crashes, etc.). At
 * that point we cannot rely on app-level styles, fonts, or providers
 * being available, so we render a deliberately barebones inline-styled
 * page. The only goal is: tell the user what happened, give them a
 * support reference, offer a hard reload.
 *
 * `global-error.tsx` MUST include its own `<html>` and `<body>` tags
 * (per Next.js docs): it's rendered as the entire document.
 *
 * Keep the public site's night palette available without root styles.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const errorId = useMemo(() => buildErrorId(), [error]);

  useEffect(() => {
    console.error("[global-error]", { errorId, digest: error.digest, error });
    try {
      captureBrowserException(error, {
        error_id: errorId,
        route_segment: "global",
        digest: error.digest,
        fatal: true,
      });
    } catch {
      /* swallow */
    }
  }, [error, errorId]);

  const sans =
    "'Instrument Sans', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
  const mono = "ui-monospace, SFMono-Regular, Menlo, monospace";

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          padding: 0,
          minHeight: "100vh",
          fontFamily: sans,
          background: "oklch(0.16 0.018 160)",
          color: "oklch(0.94 0.016 148)",
          WebkitFontSmoothing: "antialiased",
        }}
      >
        <main
          role="alert"
          aria-live="assertive"
          style={{
            maxWidth: 544,
            margin: "0 auto",
            padding: "96px 24px",
          }}
        >
          <p
            aria-hidden="true"
            style={{
              marginTop: 24,
              fontFamily: sans,
              fontSize: "clamp(80px, 16vw, 144px)",
              lineHeight: 0.9,
              letterSpacing: "-0.04em",
              fontWeight: 400,
              color: "oklch(0.94 0.016 148)",
            }}
          >
            500
          </p>
          <h1
            style={{
              marginTop: 32,
              marginBottom: 0,
              fontFamily: sans,
              fontSize: 32,
              fontWeight: 400,
              lineHeight: 1.15,
              letterSpacing: "-0.02em",
              color: "oklch(0.94 0.016 148)",
            }}
          >
            Papercrane couldn’t load.
          </h1>
          <p
            style={{
              marginTop: 16,
              fontSize: 15,
              lineHeight: 1.6,
              color: "oklch(0.73 0.028 152)",
            }}
          >
            Try again. If it keeps happening, share the reference below with
            support.
          </p>
          <div
            style={{
              marginTop: 32,
            }}
          >
            <span
              style={{
                fontFamily: mono,
                fontSize: 11,
                color: "oklch(0.73 0.028 152)",
              }}
            >
              Reference id
            </span>
            <code
              style={{
                marginTop: 6,
                display: "block",
                fontFamily: mono,
                fontSize: 15,
                color: "oklch(0.94 0.016 148)",
                wordBreak: "break-all",
              }}
            >
              {errorId}
            </code>
            {error.digest && (
              <span
                style={{
                  marginTop: 8,
                  display: "block",
                  fontFamily: mono,
                  fontSize: 11,
                  color: "oklch(0.73 0.028 152)",
                }}
              >
                digest: {error.digest}
              </span>
            )}
          </div>
          <div
            style={{
              marginTop: 40,
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 24,
            }}
          >
            <button
              type="button"
              onClick={reset}
              autoFocus
              style={{
                padding: "12px 24px",
                borderRadius: 999,
                background: "oklch(0.81 0.10 153)",
                color: "oklch(0.16 0.018 160)",
                border: "none",
                fontFamily: sans,
                fontSize: 15,
                fontWeight: 500,
                letterSpacing: "-0.01em",
                cursor: "pointer",
              }}
            >
              Try again
            </button>
            <a
              href={`mailto:support@papercrane.bio?subject=${encodeURIComponent(`Fatal error ${errorId}`)}`}
              style={{
                fontFamily: sans,
                fontSize: 14,
                color: "oklch(0.73 0.028 152)",
                textDecoration: "none",
                textUnderlineOffset: 4,
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.textDecoration = "underline";
                e.currentTarget.style.color = "oklch(0.94 0.016 148)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.textDecoration = "none";
                e.currentTarget.style.color = "oklch(0.73 0.028 152)";
              }}
            >
              Contact support
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
