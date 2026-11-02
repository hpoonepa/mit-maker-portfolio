"use client";

import { useMemo, useState } from "react";

/**
 * Hand-rolled SVG scatter: ipTM (x) vs pAE (y), colored by tool.
 *
 * Recharts isn't in the dependency tree (Wave 13 standardised on
 * Mol* + hand-rolled SVG to keep bundle weight off the dashboard
 * routes), so this draws straight to <svg>.
 */

export interface ScatterDatum {
  id: string;
  ipTM: number;
  pAE: number;
  tool?: string;
  rank?: number | null;
}

export interface DesignScatterPlotProps {
  data: ScatterDatum[];
  /** Optional id of the currently-selected design: drawn as a ring. */
  highlightId?: string | null;
  onHover?: (id: string | null) => void;
  onClick?: (id: string) => void;
  /** Bounds: defaults match the canonical metric ranges. */
  xDomain?: [number, number];
  yDomain?: [number, number];
}

const TOOL_PALETTE: Array<{ stroke: string; fill: string }> = [
  { stroke: "#14110d", fill: "rgba(20, 17, 13, 0.7)" }, // ink
  { stroke: "#b8845a", fill: "rgba(184, 132, 90, 0.75)" }, // crane
  { stroke: "#7a8e6f", fill: "rgba(122, 142, 111, 0.75)" }, // sage
  { stroke: "#8a6cb4", fill: "rgba(138, 108, 180, 0.75)" }, // violet
  { stroke: "#c0633d", fill: "rgba(192, 99, 61, 0.75)" }, // ember
];

const PAD = { top: 16, right: 18, bottom: 36, left: 44 };

export function DesignScatterPlot({
  data,
  highlightId,
  onHover,
  onClick,
  xDomain = [0, 1],
  yDomain = [0, 30],
}: DesignScatterPlotProps) {
  const [width, setWidth] = useState(420);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const height = 320;

  const palette = useMemo(() => {
    const tools = Array.from(new Set(data.map((d) => d.tool ?? "unknown")));
    const map = new Map<string, (typeof TOOL_PALETTE)[number]>();
    tools.forEach((t, i) =>
      map.set(t, TOOL_PALETTE[i % TOOL_PALETTE.length]!),
    );
    return { tools, map };
  }, [data]);

  const innerW = Math.max(0, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const xScale = (v: number) =>
    PAD.left + ((v - xDomain[0]) / (xDomain[1] - xDomain[0])) * innerW;
  const yScale = (v: number) =>
    PAD.top + ((v - yDomain[0]) / (yDomain[1] - yDomain[0])) * innerH;

  const xTicks = ticks(xDomain[0], xDomain[1], 5);
  const yTicks = ticks(yDomain[0], yDomain[1], 5);

  const hoverDatum = data.find((d) => d.id === hoverId) ?? null;

  return (
    <div className="p-5">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="font-sans text-[12px] text-graphite">
            ipTM × pAE
          </h3>
          <p className="mt-1 font-sans text-[12px] text-graphite-soft">
            Model confidence: ipTM and predicted aligned error (Å).
          </p>
        </div>
        <span className="font-mono text-[11px] text-graphite-soft tabular-nums">
          n = {data.length}
        </span>
      </div>

      <div
        className="relative mt-4"
        ref={(el) => {
          if (el && el.clientWidth && Math.abs(el.clientWidth - width) > 2) {
            setWidth(el.clientWidth);
          }
        }}
      >
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Scatter plot of ipTM versus pAE for ${data.length} designs`}
        >
          {/* Y grid */}
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="#e7e0d2"
                strokeDasharray="2 4"
              />
              <text
                x={PAD.left - 8}
                y={yScale(t)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-graphite-soft font-mono"
                style={{ fontSize: 10 }}
              >
                {t.toFixed(0)}
              </text>
            </g>
          ))}
          {/* X grid */}
          {xTicks.map((t) => (
            <g key={`x${t}`}>
              <line
                x1={xScale(t)}
                x2={xScale(t)}
                y1={PAD.top}
                y2={height - PAD.bottom}
                stroke="#e7e0d2"
                strokeDasharray="2 4"
              />
              <text
                x={xScale(t)}
                y={height - PAD.bottom + 16}
                textAnchor="middle"
                className="fill-graphite-soft font-mono"
                style={{ fontSize: 10 }}
              >
                {t.toFixed(2)}
              </text>
            </g>
          ))}

          {/* Axis labels */}
          <text
            x={PAD.left + innerW / 2}
            y={height - 6}
            textAnchor="middle"
            className="fill-graphite font-mono"
            style={{ fontSize: 10, letterSpacing: "0.18em" }}
          >
            IPTM →
          </text>
          <text
            x={-PAD.top - innerH / 2}
            y={12}
            transform="rotate(-90)"
            textAnchor="middle"
            className="fill-graphite font-mono"
            style={{ fontSize: 10, letterSpacing: "0.18em" }}
          >
            ← PAE
          </text>

          {/* Points */}
          {data.map((d) => {
            const color =
              palette.map.get(d.tool ?? "unknown") ?? TOOL_PALETTE[0]!;
            const isHover = hoverId === d.id;
            const isSelected = highlightId === d.id;
            return (
              <circle
                key={d.id}
                cx={xScale(clamp(d.ipTM, xDomain[0], xDomain[1]))}
                cy={yScale(clamp(d.pAE, yDomain[0], yDomain[1]))}
                r={isSelected ? 7 : isHover ? 5.5 : 4}
                fill={color.fill}
                stroke={isSelected ? "#14110d" : color.stroke}
                strokeWidth={isSelected ? 2 : 1}
                style={{ cursor: onClick ? "pointer" : "default" }}
                onMouseEnter={() => {
                  setHoverId(d.id);
                  onHover?.(d.id);
                }}
                onMouseLeave={() => {
                  setHoverId(null);
                  onHover?.(null);
                }}
                onClick={() => onClick?.(d.id)}
              />
            );
          })}
        </svg>

        {hoverDatum && (
          <div
            className="pointer-events-none absolute rounded-lg border border-ink/20 bg-paper px-2.5 py-1.5 font-mono text-[10px] text-ink"
            style={{
              left: Math.min(
                xScale(clamp(hoverDatum.ipTM, xDomain[0], xDomain[1])) + 10,
                width - 140,
              ),
              top: yScale(clamp(hoverDatum.pAE, yDomain[0], yDomain[1])) - 8,
            }}
          >
            <div className="text-graphite-soft">
              {(hoverDatum.tool ?? "unknown").toString().slice(0, 24)}
            </div>
            <div className="mt-0.5">
              ipTM {hoverDatum.ipTM.toFixed(3)} · pAE{" "}
              {hoverDatum.pAE.toFixed(2)}
            </div>
          </div>
        )}
      </div>

      {palette.tools.length > 1 && (
        <div className="mt-4 flex flex-wrap gap-3 pt-3">
          {palette.tools.map((t) => {
            const color = palette.map.get(t) ?? TOOL_PALETTE[0]!;
            return (
              <div key={t} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: color.fill, border: `1px solid ${color.stroke}` }}
                />
                <span className="font-sans text-[12px] text-graphite">
                  {t.length > 28 ? t.slice(0, 28) + "…" : t}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ticks(min: number, max: number, count: number): number[] {
  if (count <= 1) return [min, max];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => +(min + step * i).toFixed(4));
}

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}
