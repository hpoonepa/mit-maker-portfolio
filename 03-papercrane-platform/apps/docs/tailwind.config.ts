import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx,md,mdx}",
    "./components/**/*.{ts,tsx,md,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#F7F4ED",
        "paper-fold": "#EEE9DE",
        "paper-deep": "#E5DED0",
        ink: "#14110D",
        "ink-soft": "#2A2621",
        crane: "#C1272D",
        "crane-deep": "#961C21",
        "crane-glow": "rgba(193, 39, 45, 0.12)",
        graphite: "#5A554D",
        "graphite-soft": "#8A857B",
        lattice: "rgba(20, 17, 13, 0.08)",
        "lattice-strong": "rgba(20, 17, 13, 0.18)",
      },
      fontFamily: {
        display: ["var(--font-fraunces)", "serif"],
        sans: ["var(--font-instrument)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "monospace"],
      },
      fontSize: {
        "display-xl": ["clamp(4rem, 11vw, 10.5rem)", { lineHeight: "0.88", letterSpacing: "-0.035em" }],
        "display-lg": ["clamp(3rem, 7vw, 6rem)", { lineHeight: "0.95", letterSpacing: "-0.03em" }],
        "display-md": ["clamp(2rem, 4.5vw, 4rem)", { lineHeight: "1.02", letterSpacing: "-0.025em" }],
        eyebrow: ["0.72rem", { lineHeight: "1", letterSpacing: "0.24em" }],
      },
    },
  },
  plugins: [],
};

export default config;
