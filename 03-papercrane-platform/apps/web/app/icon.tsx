import { ImageResponse } from "next/og";

export const runtime = "edge";

/**
 * Favicon at 32×32 — dynamically generated from the brand tokens so that
 * the Paper Crane mark stays 1:1 with `@papercrane/brand`. No binary
 * `favicon.ico` needed.
 *
 * Next.js picks this up automatically for `/icon`.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#F7F4ED",
          borderRadius: 6,
        }}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 100 100"
          width={26}
          height={26}
        >
          <path fill="#C1272D" d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z" />
          <path fill="#961C21" d="M50 18 L64 62 L50 40 Z" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
