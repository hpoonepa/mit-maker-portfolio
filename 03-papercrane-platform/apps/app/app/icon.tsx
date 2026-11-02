import { ImageResponse } from "next/og";

export const runtime = "edge";

/**
 * Favicon for the authenticated app surface (app.papercrane.bio).
 * Identical paper-crane mark; the "app" context is implied by the subdomain.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#09100c",
        borderRadius: 6,
      }}
    >
      <svg
        width={26}
        height={26}
        style={{ color: "#91d3a3" }}
        viewBox="0 0 48 40"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        aria-hidden="true"
      >
        <path d="m20 23 14-20-3 16Z" fill="currentColor" opacity=".52" />
        <path d="M20 23 11 3l20 16Z" fill="currentColor" />
        <path d="M3 18 20 23 18 31Z" fill="currentColor" opacity=".72" />
        <path d="m20 23 11-4-3 14-10-2Z" fill="currentColor" opacity=".9" />
        <path d="m28 33 7-19 5-2 6 6-7-2-2 2-5 17Z" fill="currentColor" />
        <path
          d="m20 23 8 10M20 23 31 19"
          stroke="#07100d"
          strokeWidth=".8"
          opacity=".65"
        />
      </svg>
    </div>,
    { ...size },
  );
}
