/**
 * CSS-only confetti burst.
 *
 * We deliberately avoid `canvas-confetti` so onboarding doesn't add a new
 * runtime dep. 24 paper-tone squares fall from the top, each with a
 * randomised delay/horizontal-drift via inline style. The animation lasts
 * 2.4s and then the elements unmount, so there's no lingering DOM.
 *
 * Respects `prefers-reduced-motion: reduce`: falls back to a single
 * static "✦" mark in that mode.
 */
"use client";

import { useEffect, useMemo, useState } from "react";

interface Piece {
  left: number;
  delay: number;
  duration: number;
  rotate: number;
  drift: number;
  color: string;
}

const COLORS = [
  "#c1272d", // crane
  "#7b1018", // crane-deep
  "#f3e8d2", // paper-fold
  "#262220", // ink
  "#a89171", // graphite
];

function makePiece(): Piece {
  return {
    left: Math.random() * 100,
    delay: Math.random() * 0.4,
    duration: 1.6 + Math.random() * 0.9,
    rotate: Math.random() * 360,
    drift: (Math.random() - 0.5) * 80,
    color: COLORS[Math.floor(Math.random() * COLORS.length)] ?? "#c1272d",
  };
}

export function Confetti({ count = 24, durationMs = 2400 }: { count?: number; durationMs?: number }) {
  const [visible, setVisible] = useState(true);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia) {
      setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }
    const t = setTimeout(() => setVisible(false), durationMs);
    return () => clearTimeout(t);
  }, [durationMs]);

  // Deterministic per-mount so React doesn't re-randomise on each re-render.
  const pieces = useMemo<Piece[]>(
    () => Array.from({ length: count }, () => makePiece()),
    [count],
  );

  if (!visible) return null;

  if (reduced) {
    return (
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <span className="font-display text-3xl text-crane">✦</span>
      </div>
    );
  }

  return (
    <div
      aria-hidden
      data-testid="confetti"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      <style>{`
        @keyframes paper-crane-confetti {
          0%   { transform: translate3d(0, -10vh, 0) rotate(0deg); opacity: 0; }
          10%  { opacity: 1; }
          100% { transform: translate3d(var(--drift, 0px), 110vh, 0) rotate(var(--rot, 360deg)); opacity: 0.9; }
        }
      `}</style>
      {pieces.map((p, i) => (
        <span
          key={i}
          className="absolute block h-2 w-2 rounded-[2px]"
          style={{
            left: `${p.left}%`,
            top: "-12vh",
            backgroundColor: p.color,
            animation: `paper-crane-confetti ${p.duration}s cubic-bezier(0.2, 0.7, 0.3, 1) ${p.delay}s forwards`,
            ["--drift" as string]: `${p.drift}px`,
            ["--rot" as string]: `${p.rotate}deg`,
          }}
        />
      ))}
    </div>
  );
}
