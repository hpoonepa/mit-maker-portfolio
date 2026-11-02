"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

type SeedAllocatorProps = {
  label?: string;
  seeds: number;
  onChange: (seeds: number) => void;
  min?: number;
  max?: number;
  /** Seeds remaining in the org's period: used for headroom hint. */
  remaining?: number;
  /** Seeds currently consumed this period: shown in the subtitle. */
  consumed?: number;
  /** Included seeds this period (plan quota). */
  included?: number;
  /** Error message to show under the slider (e.g., quota exceeded). */
  error?: string;
};

/**
 * Seed count slider + numeric input + period headroom hint. Uses native
 * <input type="range">: styling stays paper/ink minimal via Tailwind's
 * accent-ink on the track.
 */
export function SeedAllocator({
  label = "Seeds per job",
  seeds,
  onChange,
  min = 1,
  max = 1000,
  remaining,
  consumed,
  included,
  error,
}: SeedAllocatorProps) {
  const sliderId = useId();
  const numId = useId();

  const clamp = (n: number) => Math.min(max, Math.max(min, Math.floor(n || 0)));

  const fillPct = ((seeds - min) / (max - min)) * 100;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <label
          htmlFor={sliderId}
          className="font-sans text-[12px] text-graphite-soft"
        >
          {label}
        </label>
        <div className="font-mono text-[11px] text-graphite-soft">
          {typeof consumed === "number" && typeof included === "number" && (
            <>
              {formatNum(consumed)} / {formatNum(included)} used this period
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <input
          id={sliderId}
          type="range"
          min={min}
          max={max}
          step={1}
          value={seeds}
          onChange={(e) => onChange(clamp(Number.parseInt(e.target.value, 10)))}
          aria-invalid={Boolean(error) || undefined}
          className={cn(
            "flex-1 h-1.5 appearance-none rounded-full accent-ink cursor-pointer",
            "bg-[linear-gradient(to_right,theme(colors.ink)_var(--fill),theme(colors.lattice-strong)_var(--fill))]",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
          )}
          style={{ ["--fill" as string]: `${fillPct}%` }}
        />
        <input
          id={numId}
          type="number"
          min={min}
          max={max}
          step={1}
          value={seeds}
          onChange={(e) => onChange(clamp(Number.parseInt(e.target.value, 10)))}
          aria-label="Seeds"
          className={cn(
            "w-24 rounded-xl border bg-paper px-3 py-2 font-mono text-[14px] text-ink text-right tabular-nums",
            "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink",
            error ? "border-crane" : "border-lattice-strong",
          )}
        />
      </div>

      {typeof remaining === "number" && (
        <p className="font-sans text-[12px] text-graphite">
          {remaining <= 0 ? (
            <span className="text-crane-deep">
              No seeds remaining this period. Upgrade or wait for reset.
            </span>
          ) : (
            <>
              <span className="font-mono text-ink">{formatNum(remaining)}</span>{" "}
              seeds remaining in this period.
            </>
          )}
        </p>
      )}

      {error && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          {error}
        </p>
      )}
    </div>
  );
}

function formatNum(n: number): string {
  return n.toLocaleString("en-US");
}
