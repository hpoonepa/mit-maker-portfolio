"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type SeedMeterProps = {
  /** Seeds consumed this period. */
  consumed: number;
  /** Seeds included in current plan. */
  included: number;
  /** Forecast seeds for end-of-period (drives the projection arc). */
  forecast: number;
  /** Period end ISO string for the "X days remaining" hint. */
  periodEnd: string;
  className?: string;
};

/**
 * Large circular meter showing seeds consumed vs cap, with a secondary
 * dashed arc rendering the projection (forecast). Yellow at 80%, red at
 * 95%. Pure SVG + Tailwind: no chart deps.
 */
export function SeedMeter({
  consumed,
  included,
  forecast,
  periodEnd,
  className,
}: SeedMeterProps) {
  const pct = included > 0 ? consumed / included : 0;
  const forecastPct = included > 0 ? forecast / included : 0;
  const overage = Math.max(consumed - included, 0);

  const RADIUS = 96;
  const STROKE = 14;
  const SIZE = (RADIUS + STROKE) * 2;
  const CIRC = 2 * Math.PI * RADIUS;
  const dash = Math.min(pct, 1) * CIRC;
  const projDash = Math.min(forecastPct, 1) * CIRC;

  const tone =
    pct >= 0.95 || forecastPct > 1.1
      ? "danger"
      : pct >= 0.8 || forecastPct > 1
        ? "warn"
        : "calm";

  const ringClass =
    tone === "danger"
      ? "stroke-crane"
      : tone === "warn"
        ? "stroke-amber-500"
        : "stroke-ink";

  const animatedConsumed = useCountUp(consumed);
  const daysLeft = daysUntil(periodEnd);

  return (
    <div
      className={cn(
        "p-7",
        className,
      )}
    >
      <div className="flex flex-col items-start gap-7 md:flex-row md:items-center">
        <div className="relative shrink-0">
          <svg
            width={SIZE}
            height={SIZE}
            viewBox={`0 0 ${SIZE} ${SIZE}`}
            aria-hidden="true"
          >
            {/* Background ring */}
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              className="stroke-lattice"
            />
            {/* Projection arc: dashed, behind the consumed arc */}
            {forecast > consumed && (
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                strokeWidth={STROKE - 4}
                strokeLinecap="round"
                strokeDasharray={`${projDash} ${CIRC}`}
                transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
                className={cn(
                  "opacity-40",
                  tone === "danger" ? "stroke-crane" : "stroke-graphite-soft",
                )}
                style={{
                  strokeDasharray: `4 6`,
                  strokeDashoffset: -((1 - Math.min(forecastPct, 1)) * CIRC),
                }}
              />
            )}
            {/* Consumed arc */}
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${dash} ${CIRC}`}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
              className={cn(
                "transition-[stroke-dasharray] duration-700 ease-out",
                ringClass,
              )}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className="font-sans font-medium text-[44px] leading-none tracking-[-0.02em] text-ink">
              {Math.round(pct * 100)}
              <span className="font-sans text-[16px] text-graphite-soft">%</span>
            </div>
            <div className="mt-1 font-sans text-[12px] text-graphite-soft">
              of plan used
            </div>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <div className="font-sans text-[12px] text-graphite-soft">
            Seeds this period
          </div>
          <div className="mt-2 font-sans font-medium text-display-md text-ink">
            {formatCount(animatedConsumed)}
            <span className="font-sans text-[20px] text-graphite">
              {" / "}
              {formatCount(included)}
            </span>
          </div>

          <dl className="mt-5 grid grid-cols-3 gap-5">
            <Stat
              label="Forecast"
              value={formatCount(forecast)}
              tone={forecastPct > 1.1 ? "danger" : "calm"}
            />
            <Stat label="Days left" value={String(daysLeft)} />
            <Stat
              label="Overage"
              value={overage > 0 ? formatCount(overage) : "N/A"}
              tone={overage > 0 ? "danger" : "calm"}
            />
          </dl>

          {tone === "warn" && (
            <p className="mt-5 font-sans text-[13px] text-amber-700">
              Approaching plan cap: consider a top-up pack to avoid overage
              billing.
            </p>
          )}
          {tone === "danger" && (
            <p className="mt-5 font-sans text-[13px] text-crane-deep">
              At or above 95% of plan. Forecast trajectory exceeds cap.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "calm",
}: {
  label: string;
  value: string;
  tone?: "calm" | "danger";
}) {
  return (
    <div>
      <dt className="font-sans text-[12px] text-graphite-soft">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 font-sans tabular-nums text-[18px] leading-tight tracking-[-0.01em]",
          tone === "danger" ? "text-crane-deep" : "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Animates a number from 0 → target over ~700ms using requestAnimationFrame.
 * Honors `prefers-reduced-motion`.
 */
function useCountUp(target: number, durationMs = 700): number {
  const [n, setN] = useState(0);
  const start = useRef<number | null>(null);
  const raf = useRef<number | null>(null);
  useEffect(() => {
    if (typeof window === "undefined") {
      setN(target);
      return;
    }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setN(target);
      return;
    }
    start.current = null;
    const step = (ts: number) => {
      if (start.current === null) start.current = ts;
      const t = Math.min(1, (ts - start.current) / durationMs);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      setN(Math.round(target * eased));
      if (t < 1) raf.current = window.requestAnimationFrame(step);
    };
    raf.current = window.requestAnimationFrame(step);
    return () => {
      if (raf.current !== null) window.cancelAnimationFrame(raf.current);
    };
  }, [target, durationMs]);
  return n;
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / 86_400_000));
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toString();
}
