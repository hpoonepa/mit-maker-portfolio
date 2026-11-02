"use client";

/**
 * Hero metric rail — a slow horizontal ticker of social-proof metrics.
 *
 * Reuses the existing `animate-marquee` keyframe defined in
 * `tailwind.config.ts`. We pause the animation on hover via the `paused`
 * state — flipping `animationPlayState` is enough; no JS rAF loop required.
 */
import { useState } from "react";

const METRICS = [
  { value: "12", label: "tools, one rubric" },
  { value: "1,000", label: "seeds per wish" },
  { value: "3", label: "pre-registered targets" },
  { value: "AUC 0.806", label: "ipSAE on holdout" },
  { value: "1", label: "API key" },
  { value: "0", label: "Conda envs" },
];

export function MetricRail() {
  const [paused, setPaused] = useState(false);
  // Duplicate the list once so the marquee loop is seamless.
  const rail = [...METRICS, ...METRICS];

  return (
    <div
      role="region"
      aria-label="Paper Crane metrics"
      className="relative overflow-hidden marquee py-3 border-y border-lattice/70 bg-paper-fold/20"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div
        className="flex items-center gap-12 animate-marquee whitespace-nowrap"
        style={{
          animationPlayState: paused ? "paused" : "running",
          animationDuration: "42s",
        }}
      >
        {rail.map((m, i) => (
          <span
            key={i}
            className="flex items-baseline gap-2 font-display tracking-tight"
          >
            <span className="text-[20px] md:text-[22px] text-ink tabular">
              {m.value}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-graphite">
              {m.label}
            </span>
            <span
              aria-hidden="true"
              className="ml-12 inline-block w-1 h-1 rounded-full bg-crane/50"
            />
          </span>
        ))}
      </div>
    </div>
  );
}

export default MetricRail;
