import { ImageResponse } from "next/og";

export const runtime = "edge";

/**
 * Apple touch icon — 180×180. Same crane mark, sized for iOS home-screen.
 */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
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
          borderRadius: 40,
        }}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 100 100"
          width={140}
          height={140}
        >
          <path fill="#C1272D" d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z" />
          <path fill="#961C21" d="M50 18 L64 62 L50 40 Z" />
          <circle cx="62" cy="40" r="2.4" fill="#F7F4ED" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
