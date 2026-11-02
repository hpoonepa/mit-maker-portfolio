import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

export const runtime = "edge";

const SIZE = { width: 1200, height: 630 } as const;

const TRUNC = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

/**
 * Dynamic Open Graph image.
 *
 *   /api/og?title=Pricing&desc=Three%20folds.%20No%20surprises.
 *
 * Renders a paper-colored 1200x630 card with the crane mark, a
 * title, an optional description, and a YC S26 chip. Tokens
 * mirror @papercrane/brand exactly. No external deps.
 */
export function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const title = TRUNC(searchParams.get("title") ?? "Paper Crane", 60);
  const desc = TRUNC(
    searchParams.get("desc") ?? "Every protein design tool. One workflow.",
    140
  );

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
          position: "relative",
        }}
      >
        {/* Top: mark + domain */}
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
            papercrane.bio
          </div>
        </div>

        {/* Headline + description */}
        <div style={{ display: "flex", flexDirection: "column", gap: 28, maxWidth: 1024 }}>
          <div
            style={{
              fontSize: title.length > 24 ? 88 : 112,
              lineHeight: 0.95,
              letterSpacing: "-0.035em",
              fontWeight: 500,
            }}
          >
            {title}
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
            {desc}
          </div>
        </div>

        {/* Bottom: tools strip + YC tag */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontFamily: "Helvetica, Arial, sans-serif",
          }}
        >
          <div
            style={{
              display: "flex",
              gap: 24,
              fontSize: 20,
              color: "#5A554D",
              letterSpacing: "0.04em",
            }}
          >
            <span>RFdiffusion</span>
            <span style={{ color: "#C1272D" }}>·</span>
            <span>BindCraft</span>
            <span style={{ color: "#C1272D" }}>·</span>
            <span>Boltz-2</span>
            <span style={{ color: "#C1272D" }}>·</span>
            <span>Chai-1</span>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontSize: 18,
              color: "#14110D",
              border: "1px solid rgba(20,17,13,0.18)",
              padding: "10px 18px",
              borderRadius: 999,
              background: "rgba(247,244,237,0.6)",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: "#C1272D",
              }}
            />
            YC&nbsp;S26
          </div>
        </div>
      </div>
    ),
    { ...SIZE }
  );
}
