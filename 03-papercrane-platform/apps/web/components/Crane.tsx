import type { SVGProps } from "react";

/**
 * Crane — the Paper Crane mark as a standalone React component.
 *
 * Mirrors `@papercrane/brand`'s `logoSvg` paths 1:1 so the glyph stays
 * consistent across the app. Uses `currentColor` for the body fill so it
 * inherits the surrounding text color (e.g. `text-ink`, `text-crane`).
 *
 * Existing components in this app (e.g. Navbar) inline their own `CraneMark`,
 * but new code should prefer this canonical component.
 */
export function Crane(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Paper Crane"
      {...props}
    >
      <path
        fill="currentColor"
        d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z"
      />
      <path
        fill="#961C21"
        d="M50 18 L64 62 L50 40 Z"
      />
      <circle cx="62" cy="40" r="2.4" fill="#F7F4ED" />
    </svg>
  );
}

export default Crane;
