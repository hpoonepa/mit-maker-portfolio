"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

export interface RangeSliderProps {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: { min: number; max: number };
  onChange: (next: { min: number; max: number }) => void;
  format?: (n: number) => string;
  className?: string;
}

/**
 * Dual-thumb numeric range slider built from two stacked native
 * <input type="range"> elements. Native = free a11y + keyboard support.
 */
export function RangeSlider({
  label,
  min,
  max,
  step = 1,
  value,
  onChange,
  format,
  className,
}: RangeSliderProps) {
  const id = useId();
  const fmt = format ?? ((n: number) => String(n));

  const lo = Math.max(min, Math.min(value.min, value.max));
  const hi = Math.min(max, Math.max(value.min, value.max));

  const span = max - min;
  const loPct = span > 0 ? ((lo - min) / span) * 100 : 0;
  const hiPct = span > 0 ? ((hi - min) / span) * 100 : 100;

  const setLo = (n: number) => {
    const next = Math.min(n, hi);
    onChange({ min: next, max: hi });
  };
  const setHi = (n: number) => {
    const next = Math.max(n, lo);
    onChange({ min: lo, max: next });
  };

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between">
        <label
          htmlFor={`${id}-lo`}
          className="font-sans text-[12px] text-graphite-soft"
        >
          {label}
        </label>
        <span className="font-mono text-[11px] text-ink tabular-nums">
          {fmt(lo)} – {fmt(hi)}
        </span>
      </div>
      <div className="relative h-6">
        {/* track */}
        <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-lattice" />
        {/* selected band */}
        <div
          className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-ink"
          style={{ left: `${loPct}%`, right: `${100 - hiPct}%` }}
        />
        <input
          id={`${id}-lo`}
          type="range"
          aria-label={`${label} minimum`}
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => setLo(Number(e.target.value))}
          className="dual-range absolute inset-x-0 top-0 h-6 w-full appearance-none bg-transparent"
        />
        <input
          id={`${id}-hi`}
          type="range"
          aria-label={`${label} maximum`}
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => setHi(Number(e.target.value))}
          className="dual-range absolute inset-x-0 top-0 h-6 w-full appearance-none bg-transparent"
        />
      </div>
      <style jsx>{`
        .dual-range {
          pointer-events: none;
        }
        .dual-range::-webkit-slider-thumb {
          pointer-events: auto;
          appearance: none;
          width: 14px;
          height: 14px;
          border-radius: 9999px;
          background: #fdfbf6;
          border: 1.5px solid #1a1a1a;
          cursor: grab;
          margin-top: -6px;
        }
        .dual-range::-moz-range-thumb {
          pointer-events: auto;
          width: 14px;
          height: 14px;
          border-radius: 9999px;
          background: #fdfbf6;
          border: 1.5px solid #1a1a1a;
          cursor: grab;
        }
        .dual-range::-webkit-slider-runnable-track {
          background: transparent;
          height: 3px;
        }
        .dual-range::-moz-range-track {
          background: transparent;
          height: 3px;
        }
      `}</style>
    </div>
  );
}
