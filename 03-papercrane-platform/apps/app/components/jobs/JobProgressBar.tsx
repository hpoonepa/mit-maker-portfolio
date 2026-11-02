"use client";

import { cn } from "@/lib/utils";

/**
 * Slim, paper-tinted progress bar for the wait screen.
 *
 * Two modes:
 *   - Determinate: `completed / total` known → solid crane fill grows.
 *   - Indeterminate: `total === 0` or before any design completes →
 *     marquee shimmer slides across the bar so the user sees the page
 *     is alive even when there's nothing concrete to report.
 *
 * Visual contract matches the design tokens in `tailwind.config.ts` -
 * no new colors introduced. Indeterminate animation reuses the existing
 * `marquee` keyframe (already declared in tailwind config).
 */
export interface JobProgressBarProps {
  /** Designs finished so far. */
  completed: number;
  /** Total designs requested. */
  total: number;
  /** Force indeterminate even when we know totals (e.g. status='queued'). */
  indeterminate?: boolean;
  className?: string;
  /** Optional label rendered above the bar. Defaults to "X of Y seeds". */
  label?: string;
}

export function JobProgressBar({
  completed,
  total,
  indeterminate,
  className,
  label,
}: JobProgressBarProps) {
  const isDeterminate = !indeterminate && total > 0;
  const pct = isDeterminate
    ? Math.min(100, Math.max(0, Math.round((completed / total) * 100)))
    : 0;
  const displayLabel =
    label ??
    (total > 0
      ? `${completed} of ${total} designs complete`
      : "Starting up");

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-sans text-[12px] text-graphite-soft">
          Progress
        </span>
        <span className="font-sans text-sm tabular-nums text-ink">
          {displayLabel}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={isDeterminate ? 100 : undefined}
        aria-valuenow={isDeterminate ? pct : undefined}
        aria-label={`Job progress: ${displayLabel}`}
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-paper-fold"
      >
        {isDeterminate ? (
          <span
            aria-hidden
            className="block h-full rounded-full bg-crane transition-[width] duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        ) : (
          <span
            aria-hidden
            className="absolute inset-y-0 left-0 block h-full w-1/3 rounded-full bg-crane/75 motion-safe:animate-marquee motion-reduce:opacity-60"
            style={{ animationDuration: "2.2s" }}
          />
        )}
      </div>
    </div>
  );
}

export default JobProgressBar;
