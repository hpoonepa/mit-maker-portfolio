import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "Paper Crane App: Run protein binder design campaigns.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Dashboard OG image. Used for shareable job permalinks, leaderboard
 * entries, and any org-level public link. Keeps the same visual language
 * as the marketing OG but with an "App" badge so previews are distinct.
 */
export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "72px 88px",
        background: "#F7F4ED",
        fontFamily: "Georgia, serif",
        color: "#14110D",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 100 100"
            width={72}
            height={72}
          >
            <path
              fill="#C1272D"
              d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z"
            />
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
            app.papercrane.bio
          </div>
        </div>
        <div
          style={{
            fontFamily: "Helvetica, Arial, sans-serif",
            fontSize: 18,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "#F7F4ED",
            background: "#C1272D",
            padding: "10px 18px",
            borderRadius: 6,
          }}
        >
          App
        </div>
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 32,
          maxWidth: 980,
        }}
      >
        <div
          style={{
            fontSize: 120,
            lineHeight: 0.95,
            letterSpacing: "-0.035em",
            fontWeight: 500,
          }}
        >
          Paper Crane
        </div>
        <div
          style={{
            fontFamily: "Helvetica, Arial, sans-serif",
            fontSize: 40,
            lineHeight: 1.2,
            color: "#2A2621",
            maxWidth: 900,
          }}
        >
          Run protein design tools and compare results.
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "Helvetica, Arial, sans-serif",
        }}
      >
        <div
          style={{ display: "flex", gap: 28, fontSize: 22, color: "#5A554D" }}
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
            padding: "8px 14px",
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
          One workflow
        </div>
      </div>
    </div>,
    { ...size },
  );
}
