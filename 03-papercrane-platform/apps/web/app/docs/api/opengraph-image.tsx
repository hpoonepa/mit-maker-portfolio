import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Paper Crane — API Reference";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * OG image for /docs/api. Edge-safe: system serif fallback only.
 */
export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 88px",
          background:
            "radial-gradient(ellipse at 18% 12%, rgba(193,39,45,0.14), transparent 55%), radial-gradient(ellipse at 82% 78%, rgba(20,17,13,0.06), transparent 60%), #F7F4ED",
          fontFamily: "Georgia, serif",
          color: "#14110D",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width={64} height={64}>
            <path fill="#C1272D" d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z" />
            <path fill="#961C21" d="M50 18 L64 62 L50 40 Z" />
            <circle cx="62" cy="40" r="2.4" fill="#F7F4ED" />
          </svg>
          <div
            style={{
              fontFamily: "Helvetica, Arial, sans-serif",
              fontSize: 20,
              letterSpacing: "0.24em",
              textTransform: "uppercase",
              color: "#5A554D",
            }}
          >
            papercrane.bio / docs / api
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 28, maxWidth: 1024 }}>
          <div style={{ fontSize: 120, lineHeight: 0.95, letterSpacing: "-0.035em", fontWeight: 500 }}>
            API Reference
          </div>
          <div
            style={{
              fontFamily: "Helvetica, Arial, sans-serif",
              fontSize: 36,
              lineHeight: 1.2,
              color: "#2A2621",
              maxWidth: 980,
            }}
          >
            REST endpoints for design, fold, score, and rank — typed, idempotent, and rate-fair.
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: "Helvetica, Arial, sans-serif" }}>
          <div style={{ fontSize: 20, color: "#5A554D", letterSpacing: "0.04em", fontFamily: "Menlo, Consolas, monospace" }}>
            POST&nbsp;/v1/design&nbsp;&nbsp;·&nbsp;&nbsp;GET&nbsp;/v1/runs/:id
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 18, color: "#14110D", border: "1px solid rgba(20,17,13,0.18)", padding: "10px 18px", borderRadius: 999, background: "rgba(247,244,237,0.6)" }}>
            <span style={{ width: 8, height: 8, borderRadius: 999, background: "#C1272D" }} />
            YC&nbsp;S26
          </div>
        </div>
      </div>
    ),
    { ...size }
  );
}
