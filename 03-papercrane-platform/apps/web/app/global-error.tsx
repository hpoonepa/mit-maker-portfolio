"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (typeof console !== "undefined") {
      console.error(error);
    }
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          backgroundColor: "#F7F4ED",
          color: "#14110D",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "48px 24px",
          textAlign: "center",
          fontFamily:
            '"Inter", system-ui, -apple-system, sans-serif',
        }}
      >
        <div style={{ maxWidth: "640px", width: "100%" }}>
          <h1
            style={{
              fontFamily:
                '"Fraunces", Georgia, "Times New Roman", serif',
              fontWeight: 400,
              fontSize: "clamp(96px, 18vw, 168px)",
              lineHeight: 0.9,
              letterSpacing: "-0.04em",
              margin: 0,
              color: "#14110D",
            }}
          >
            500
          </h1>
          <p
            style={{
              fontFamily:
                '"Fraunces", Georgia, "Times New Roman", serif',
              fontSize: "clamp(20px, 2.4vw, 28px)",
              fontWeight: 400,
              lineHeight: 1.3,
              margin: "32px 0 12px",
              color: "#14110D",
            }}
          >
            The page could not be rendered.
          </p>
          <p
            style={{
              fontSize: "16px",
              lineHeight: 1.5,
              margin: "0 0 40px",
              color: "rgba(20, 17, 13, 0.65)",
            }}
          >
            A critical error interrupted the layout. Please retry or
            return home.
          </p>
          <div
            style={{
              display: "flex",
              gap: "24px",
              justifyContent: "center",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <button
              onClick={() => reset()}
              style={{
                fontSize: "15px",
                fontWeight: 500,
                color: "rgba(20, 17, 13, 0.7)",
                background: "transparent",
                border: "none",
                borderBottom: "1px solid rgba(20, 17, 13, 0.3)",
                paddingBottom: "2px",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              Try again
            </button>
            <Link
              href="/"
              style={{
                display: "inline-block",
                fontSize: "15px",
                fontWeight: 500,
                color: "#C1272D",
                textDecoration: "none",
                borderBottom: "1px solid #C1272D",
                paddingBottom: "2px",
              }}
            >
              Back to home →
            </Link>
          </div>
          <div
            style={{
              marginTop: "64px",
              fontFamily:
                '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
              fontSize: "12px",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "rgba(20, 17, 13, 0.45)",
            }}
          >
            status 500 · {error?.digest ?? "fatal_error"}
          </div>
        </div>
      </body>
    </html>
  );
}
