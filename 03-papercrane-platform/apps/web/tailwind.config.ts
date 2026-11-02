import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
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
        // Bumped from #8A857B (3.5:1) to #6E695E (~4.6:1) for WCAG AA on paper (#F7F4ED)
        "graphite-soft": "#6E695E",
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
        "eyebrow": ["0.72rem", { lineHeight: "1", letterSpacing: "0.24em" }],
      },
      spacing: {
        "section": "clamp(6rem, 12vh, 10rem)",
      },
      animation: {
        "fade-up": "fadeUp 0.9s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fadeIn 1.2s ease-out both",
        "pulse-dot": "pulseDot 2.6s ease-in-out infinite",
        "unfold": "unfold 1.4s cubic-bezier(0.22, 1, 0.36, 1) both",
        "drift": "drift 14s ease-in-out infinite",
        "marquee": "marquee 48s linear infinite",
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
          "0%": { transform: "perspective(800px) rotateX(80deg) translateY(40px)", opacity: "0" },
          "100%": { transform: "perspective(800px) rotateX(0deg) translateY(0)", opacity: "1" },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0,0,0)" },
          "50%": { transform: "translate3d(12px, -18px, 0)" },
        },
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      backgroundImage: {
        "paper-grain": "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 240 240' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.95' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.08 0 0 0 0 0.07 0 0 0 0 0.05 0 0 0 0.12 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        "radial-warm": "radial-gradient(ellipse at 30% 20%, rgba(193,39,45,0.06), transparent 50%), radial-gradient(ellipse at 80% 70%, rgba(20,17,13,0.04), transparent 60%)",
      },
    },
  },
  plugins: [],
};

export default config;
