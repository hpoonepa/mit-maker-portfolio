/**
 * @papercrane/brand
 *
 * Single source of truth for Paper Crane brand tokens.
 * Mirrors the Tailwind config in both apps/web and apps/app so that any
 * headless context (OG routes, email templates, CLI output, etc.) can
 * render with the exact same palette.
 */

export const colors = {
  /** Primary surface — warm off-white, the "paper" of origami. */
  paper: "#F7F4ED",
  /** Folded paper shadow — used for secondary surfaces and cards. */
  paperFold: "#EEE9DE",
  /** Deep paper — for pressed / recessed states. */
  paperDeep: "#E5DED0",
  /** Near-black, warm-toned ink for primary type. */
  ink: "#14110D",
  /** Softer ink for secondary copy. */
  inkSoft: "#2A2621",
  /** The Paper Crane red. Accent + logo fill. */
  crane: "#C1272D",
  /** Pressed crane red for hover / active. */
  craneDeep: "#961C21",
  /** Glow overlay (rgba) — used for radial washes behind the mark. */
  craneGlow: "rgba(193, 39, 45, 0.12)",
  /** Neutral graphite for muted UI. */
  graphite: "#5A554D",
  /** Softer graphite for tertiary type. */
  graphiteSoft: "#8A857B",
  /** Hairline grid overlay. */
  lattice: "rgba(20, 17, 13, 0.08)",
  /** Stronger grid lines. */
  latticeStrong: "rgba(20, 17, 13, 0.18)",
} as const;

export type ColorToken = keyof typeof colors;

export const typography = {
  display: {
    family: "Fraunces, serif",
    cssVar: "var(--font-fraunces)",
  },
  sans: {
    family: "Instrument Sans, system-ui, sans-serif",
    cssVar: "var(--font-instrument)",
  },
  mono: {
    family: "JetBrains Mono, monospace",
    cssVar: "var(--font-jetbrains)",
  },
} as const;

export const brand = {
  name: "Paper Crane",
  tagline: "Every protein design tool. One workflow.",
  domain: "papercrane.bio",
  url: "https://papercrane.bio",
  description:
    "Benchmark, run, and compare protein binder design tools — RFdiffusion, BindCraft, Boltz-2, Chai-1, and more — under one reproducible methodology.",
} as const;

/**
 * The paper-crane mark as a standalone SVG string.
 * viewBox is 100x100 so consumers can trivially scale from 16px → 512px.
 * Usable from:
 *   - React: `<div dangerouslySetInnerHTML={{ __html: logoSvg }} />`
 *   - Next.js ImageResponse (tw="...") via the <Logo /> component
 *   - Plain HTML / email templates: inline the string directly
 */
export const logoSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Paper Crane"><path fill="${colors.crane}" d="M8 58 L50 18 L92 58 L64 62 L50 88 L36 62 Z"/><path fill="${colors.craneDeep}" d="M50 18 L64 62 L50 40 Z"/><circle cx="62" cy="40" r="2.4" fill="${colors.paper}"/></svg>`;

export { Logo } from "./logo";
export type { LogoProps, LogoVariant } from "./logo";
