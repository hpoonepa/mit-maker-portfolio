import type { CSSProperties, SVGProps } from "react";
import { colors } from "./index";

export type LogoVariant = "mark" | "wordmark" | "lockup";

export interface LogoProps extends Omit<SVGProps<SVGSVGElement>, "color"> {
  /**
   * Rendered size in pixels. For `mark` this is both width and height;
   * for `wordmark` / `lockup` it is the intrinsic height (width scales).
   * @default 32
   */
  size?: number;
  /**
   * Visual form.
   *  - `mark`: paper-crane glyph alone (square)
   *  - `wordmark`: "Paper Crane" in serif display type
   *  - `lockup`: mark + wordmark side-by-side
   * @default "mark"
   */
  variant?: LogoVariant;
  /**
   * Override the fill color of the crane glyph. Defaults to `colors.crane`.
   * Accepts any valid CSS color (hex, rgb(), currentColor, etc.).
   */
  color?: string;
  /**
   * Optional title for screen-reader / tooltip.
   * @default "Paper Crane"
   */
  title?: string;
}

/**
 * The paper-crane mark. Pure SVG — no external deps, no CSS imports.
 * Safe to render inside Next.js `ImageResponse` (next/og) and RSC.
 *
 * viewBox 0 0 100 100 → legible from 16px up to 512px.
 */
export function Logo({
  size = 32,
  variant = "mark",
  color = colors.crane,
  title = "Paper Crane",
  style,
  ...rest
}: LogoProps) {
  if (variant === "mark") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 100 100"
        width={size}
        height={size}
        role="img"
        aria-label={title}
        style={style}
        {...rest}
      >
        <title>{title}</title>
        {/* Origami crane silhouette — a five-point star-like fold. */}
        <path fill={color} d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z" />
        {/* Inner head-fold, slightly darker to hint dimensionality. */}
        <path fill={shade(color, -0.18)} d="M50 18 L64 62 L50 40 Z" />
        {/* Eye — a tiny paper speck. */}
        <circle cx="62" cy="40" r="2.4" fill={colors.paper} />
      </svg>
    );
  }

  if (variant === "wordmark") {
    const height = size;
    const width = height * 5.2;
    const fontSize = height * 0.82;
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="img"
        aria-label={title}
        style={style}
        {...rest}
      >
        <title>{title}</title>
        <text
          x={0}
          y={height * 0.78}
          fontFamily="Fraunces, Georgia, serif"
          fontWeight={500}
          fontSize={fontSize}
          letterSpacing={-0.02 * fontSize}
          fill={colors.ink}
        >
          Paper Crane
        </text>
      </svg>
    );
  }

  // lockup: mark + wordmark
  const markSize = size;
  const gap = size * 0.32;
  const wordHeight = size * 0.9;
  const wordWidth = wordHeight * 5.2;
  const totalWidth = markSize + gap + wordWidth;
  const fontSize = wordHeight * 0.82;
  const lockupStyle: CSSProperties = { ...style };
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${totalWidth} ${markSize}`}
      width={totalWidth}
      height={markSize}
      role="img"
      aria-label={title}
      style={lockupStyle}
      {...rest}
    >
      <title>{title}</title>
      <g>
        <path fill={color} d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z"
          transform={`scale(${markSize / 100})`} />
        <path fill={shade(color, -0.18)} d="M50 18 L64 62 L50 40 Z"
          transform={`scale(${markSize / 100})`} />
        <circle cx={62} cy={40} r={2.4} fill={colors.paper}
          transform={`scale(${markSize / 100})`} />
      </g>
      <text
        x={markSize + gap}
        y={markSize * 0.72}
        fontFamily="Fraunces, Georgia, serif"
        fontWeight={500}
        fontSize={fontSize}
        letterSpacing={-0.02 * fontSize}
        fill={colors.ink}
      >
        Paper Crane
      </text>
    </svg>
  );
}

/**
 * Tiny color shader — darkens (amount < 0) or lightens (amount > 0) a hex.
 * Kept intentionally simple; only supports 6-digit hex + named `currentColor`.
 */
function shade(hex: string, amount: number): string {
  if (!hex.startsWith("#") || hex.length !== 7) return hex;
  const num = parseInt(hex.slice(1), 16);
  const r = Math.max(0, Math.min(255, Math.round(((num >> 16) & 0xff) * (1 + amount))));
  const g = Math.max(0, Math.min(255, Math.round(((num >> 8) & 0xff) * (1 + amount))));
  const b = Math.max(0, Math.min(255, Math.round((num & 0xff) * (1 + amount))));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}
