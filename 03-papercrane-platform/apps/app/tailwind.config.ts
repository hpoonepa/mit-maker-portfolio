import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "../../packages/ui/src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Exact night palette used by papercrane.bio's route-shell.css.
      colors: {
        paper: "oklch(0.16 0.018 160 / <alpha-value>)",
        "paper-fold": "oklch(0.22 0.025 158 / <alpha-value>)",
        "paper-deep": "oklch(0.29 0.035 155 / <alpha-value>)",
        ink: "oklch(0.94 0.016 148 / <alpha-value>)",
        "ink-soft": "oklch(0.84 0.025 150 / <alpha-value>)",
        crane: "oklch(0.81 0.10 153 / <alpha-value>)",
        "crane-deep": "oklch(0.81 0.10 153 / <alpha-value>)",
        "crane-glow": "oklch(0.25 0.035 153 / <alpha-value>)",
        graphite: "oklch(0.73 0.028 152 / <alpha-value>)",
        "graphite-soft": "oklch(0.67 0.025 152 / <alpha-value>)",
        lattice: "oklch(0.30 0.025 150 / <alpha-value>)",
        "lattice-strong": "oklch(0.40 0.035 150 / <alpha-value>)",
        "surface-1": "oklch(0.16 0.018 160 / <alpha-value>)",
        "surface-2": "oklch(0.19 0.026 157 / <alpha-value>)",
        "surface-3": "oklch(0.24 0.03 155 / <alpha-value>)",
        "surface-ink": "oklch(0.94 0.016 148 / <alpha-value>)",
      },
      ringColor: { DEFAULT: "#91d3a3", crane: "#91d3a3", ink: "#e3eee5" },
      boxShadow: {
        fold: "0 16px 42px rgb(0 0 0 / 0.2)",
        "fold-sm": "0 8px 24px rgb(0 0 0 / 0.16)",
        crane: "none",
      },
      borderRadius: {
        DEFAULT: "0.75rem",
        md: "0.875rem",
        lg: "1rem",
        xl: "1.25rem",
        "2xl": "1.5rem",
        "3xl": "2rem",
      },
      fontFamily: {
        display: ["var(--font-instrument)", "system-ui", "sans-serif"],
        sans: ["var(--font-instrument)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      fontSize: {
        "display-xl": [
          "clamp(3rem, 8vw, 7rem)",
          { lineHeight: "1.05", letterSpacing: "-0.04em" },
        ],
        "display-lg": [
          "clamp(2.5rem, 5vw, 4.5rem)",
          { lineHeight: "1.08", letterSpacing: "-0.035em" },
        ],
        "display-md": [
          "clamp(1.875rem, 3vw, 2.75rem)",
          { lineHeight: "1.15", letterSpacing: "-0.03em" },
        ],
        eyebrow: ["0.8125rem", { lineHeight: "1.4", letterSpacing: "0" }],
      },
      spacing: { section: "clamp(6rem, 12vh, 10rem)" },
      animation: {
        "fade-up": "fadeUp 0.9s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fadeIn 1.2s ease-out both",
        "pulse-dot": "pulseDot 2.6s ease-in-out infinite",
        unfold: "unfold 1.4s cubic-bezier(0.22, 1, 0.36, 1) both",
        drift: "drift 14s ease-in-out infinite",
        marquee: "marquee 48s linear infinite",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(24px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        pulseDot: {
          "0%, 100%": { transform: "scale(1)", opacity: "0.9" },
          "50%": { transform: "scale(1.6)", opacity: "0.35" },
        },
        unfold: {
          "0%": {
            transform: "perspective(800px) rotateX(80deg) translateY(40px)",
            opacity: "0",
          },
          "100%": {
            transform: "perspective(800px) rotateX(0deg) translateY(0)",
            opacity: "1",
          },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0,0,0)" },
          "50%": { transform: "translate3d(12px, -18px, 0)" },
        },
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      backgroundImage: { "paper-grain": "none" },
    },
  },
  plugins: [],
};

export default config;
