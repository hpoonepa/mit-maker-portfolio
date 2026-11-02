"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

type DayBucket = {
  day: string; // YYYY-MM-DD
  byTool: Record<string, number>;
  total: number;
};

type GpuHoursChartProps = {
  series: DayBucket[];
  totals: Record<string, number>;
  totalGpuHours: number;
  className?: string;
};

/**
 * Stacked bar chart: one bar per day in the current period, segments
 * coloured per tool. Pure SVG, no recharts/tremor (we ship without those
 * deps). Hover reveals a per-segment tooltip with the tool + hours.
 */
export function GpuHoursChart({
  series,
  totals,
  totalGpuHours,
  className,
}: GpuHoursChartProps) {
  const [hover, setHover] = useState<{
    x: number;
    y: number;
    label: string;
    value: string;
  } | null>(null);

  // Order tools by total descending so stacks read consistently.
  const tools = useMemo(
    () =>
      Object.entries(totals)
        .sort((a, b) => b[1] - a[1])
        .map(([t]) => t),
    [totals],
  );

  const toolColor = useMemo(() => buildToolPalette(tools), [tools]);

  // Per-tool max keeps low-volume tools legible alongside dominant ones.
  const max = Math.max(
    ...tools.map((t) => Math.max(...series.map((d) => d.byTool[t] ?? 0))),
    0.0001,
  );
  const W = 720;
  const H = 220;
  const padX = 28;
  const padTop = 16;
  const padBottom = 28;
  const innerW = W - padX * 2;
  const innerH = H - padTop - padBottom;
  const stepX = series.length > 1 ? innerW / (series.length - 1) : 0;
  const xAt = (i: number) => padX + i * stepX;
  const yAt = (v: number) => padTop + innerH * (1 - v / max);

  if (series.length === 0 || totalGpuHours === 0) {
    return (
      <div
        className={cn(
          "px-6 py-12 text-center",
          className,
        )}
      >
        <p className="font-sans text-[13px] text-graphite">
          No GPU hours logged this period yet.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "p-6",
        className,
      )}
    >
      <div className="flex items-end justify-between">
        <div>
          <div className="font-sans text-[12px] text-graphite-soft">
            GPU-hours by tool
          </div>
          <div className="mt-2 font-sans tabular-nums text-[28px] leading-none tracking-[-0.02em] text-ink tabular-nums">
            {totalGpuHours.toFixed(1)}
            <span className="ml-2 font-sans text-[12px] text-graphite-soft">
              hrs · this period
            </span>
          </div>
        </div>
      </div>

      <div className="relative mt-6">
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
          {/* Y gridlines */}
          {[0.25, 0.5, 0.75, 1].map((g) => {
            const y = padTop + innerH * (1 - g);
            return (
              <g key={g}>
                <line
                  x1={padX}
                  x2={W - padX}
                  y1={y}
                  y2={y}
                  className="stroke-lattice"
                  strokeWidth={1}
                />
                <text
                  x={padX - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-graphite-soft font-sans tabular-nums"
                  style={{ fontSize: 9 }}
                >
                  {(max * g).toFixed(1)}
                </text>
              </g>
            );
          })}

          {/* Hairline polylines, one per tool */}
          {tools.map((t) => {
            const pts = series
              .map((d, i) => `${xAt(i).toFixed(2)},${yAt(d.byTool[t] ?? 0).toFixed(2)}`)
              .join(" ");
            return (
              <polyline
                key={t}
                points={pts}
                fill="none"
                stroke={toolColor[t]}
                strokeWidth={1}
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            );
          })}

          {/* Hover targets: invisible columns reveal tooltip per day */}
          {series.map((d, i) => {
            const x = xAt(i) - stepX / 2;
            const colW = stepX || innerW;
            return (
              <rect
                key={`hit-${d.day}`}
                x={x}
                y={padTop}
                width={Math.max(colW, 2)}
                height={innerH}
                fill="transparent"
                onMouseEnter={(e) => {
                  const rect = (
                    e.currentTarget.ownerSVGElement as SVGSVGElement
                  ).getBoundingClientRect();
                  setHover({
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top,
                    label: formatDay(d.day),
                    value: `${d.total.toFixed(2)} hrs`,
                  });
                }}
                onMouseLeave={() => setHover(null)}
              />
            );
          })}

          {/* X axis sparse ticks */}
          {series.map((d, i) => {
            if (i % Math.max(1, Math.floor(series.length / 8)) !== 0) return null;
            const x = xAt(i);
            return (
              <text
                key={d.day}
                x={x}
                y={H - 8}
                textAnchor="middle"
                className="fill-graphite-soft font-sans tabular-nums"
                style={{ fontSize: 9 }}
              >
                {d.day.slice(8)}
              </text>
            );
          })}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 rounded-md border border-lattice bg-paper px-2.5 py-1.5 shadow-md"
            style={{
              left: Math.min(hover.x + 12, 600),
              top: hover.y - 36,
            }}
          >
            <div className="font-sans text-[12px] text-graphite">{hover.label}</div>
            <div className="font-sans tabular-nums text-[12px] text-ink">{hover.value}</div>
          </div>
        )}
      </div>

      {/* Legend */}
      <ul className="mt-5 flex flex-wrap gap-x-5 gap-y-2">
        {tools.map((t) => (
          <li key={t} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-px w-4"
              style={{ backgroundColor: toolColor[t] }}
            />
            <span className="font-sans text-[12px] text-ink">{t}</span>
            <span className="font-sans tabular-nums text-[12px] text-graphite-soft tabular-nums">
              {totals[t]?.toFixed(1)}h
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatDay(ymd: string): string {
  const [, m, d] = ymd.split("-");
  return `${m}/${d}`;
}

/**
 * Deterministic palette anchored on the brand crane red plus a cycling
 * set of muted earth tones. Order is stable for a given tool list, so
 * the legend matches the stacks across renders.
 */
function buildToolPalette(tools: string[]): Record<string, string> {
  const palette = [
    "#91d3a3", // crane
    "#2A2621", // ink-soft
    "#8A857B", // graphite-soft
    "#5A554D", // graphite
    "#A8501F", // burnt sienna
    "#6B7C3F", // moss
    "#3F5A6B", // slate blue
    "#B59A55", // ochre
    "#7A4E6B", // muted plum
    "#3F6B5A", // pine
  ];
  const out: Record<string, string> = {};
  tools.forEach((t, i) => {
    out[t] = palette[i % palette.length] ?? "#5A554D";
  });
  return out;
}
