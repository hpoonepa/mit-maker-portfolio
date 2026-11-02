"use client";

import { toolLabel } from "@/lib/results/metrics";
import { useId } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Filter state shape. Kept flat so the parent can serialise to URL
 * query params later without a helper. `null` means "no constraint". */

export interface DesignFilterState {
  ipTM: { min: number; max: number };
  pAE: { min: number; max: number };
  pDockQ: { min: number; max: number };
  tool: string | null;
}

export const DEFAULT_FILTERS: DesignFilterState = {
  ipTM: { min: 0, max: 1 },
  pAE: { min: 0, max: 30 },
  pDockQ: { min: 0, max: 1 },
  tool: null,
};

export interface DesignFiltersProps {
  value: DesignFilterState;
  onChange: (next: DesignFilterState) => void;
  /** Tools that actually appear in the current dataset: drives the chip row. */
  availableTools: string[];
  availableMetrics?: string[];
  /** Count of designs that pass the current filter, for the helper text. */
  matchCount: number;
  totalCount: number;
}

export function DesignFilters({
  value,
  onChange,
  availableTools,
  availableMetrics = [],
  matchCount,
  totalCount,
}: DesignFiltersProps) {
  const isDirty =
    value.ipTM.min !== DEFAULT_FILTERS.ipTM.min ||
    value.ipTM.max !== DEFAULT_FILTERS.ipTM.max ||
    value.pAE.min !== DEFAULT_FILTERS.pAE.min ||
    value.pAE.max !== DEFAULT_FILTERS.pAE.max ||
    value.pDockQ.min !== DEFAULT_FILTERS.pDockQ.min ||
    value.pDockQ.max !== DEFAULT_FILTERS.pDockQ.max ||
    value.tool !== null;

  return (
    <div className="p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-3.5 w-3.5 text-graphite-soft" />
          <h3 className="font-sans text-[12px] text-graphite">
            Filters
          </h3>
          <span className="font-mono text-[11px] text-graphite-soft">
            · {matchCount}/{totalCount} match
          </span>
        </div>
        {isDirty && (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="inline-flex items-center gap-1 font-sans text-[12px] text-graphite hover:text-ink transition-colors"
          >
            <X className="h-3 w-3" />
            Reset
          </button>
        )}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        {availableMetrics.includes("ipTM") && (
          <RangeSlider
            label="ipTM"
            help="higher is better"
            min={0}
            max={1}
            step={0.01}
            value={value.ipTM}
            onChange={(v) => onChange({ ...value, ipTM: v })}
          />
        )}
        {availableMetrics.includes("PAE") && (
          <RangeSlider
            label="pAE"
            help="lower is better"
            min={0}
            max={30}
            step={0.5}
            value={value.pAE}
            onChange={(v) => onChange({ ...value, pAE: v })}
          />
        )}
        {availableMetrics.includes("pDockQ") && (
          <RangeSlider
            label="pDockQ"
            help="higher is better"
            min={0}
            max={1}
            step={0.01}
            value={value.pDockQ}
            onChange={(v) => onChange({ ...value, pDockQ: v })}
          />
        )}
      </div>

      {availableTools.length > 0 && (
        <div className="mt-5 pt-4">
          <p className="font-sans text-[12px] text-graphite-soft">
            Tool
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <ToolChip
              label="All"
              active={value.tool === null}
              onClick={() => onChange({ ...value, tool: null })}
            />
            {availableTools.map((t) => (
              <ToolChip
                key={t}
                label={toolLabel(t)}
                active={value.tool === t}
                onClick={() =>
                  onChange({ ...value, tool: value.tool === t ? null : t })
                }
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Small dual-ended range slider built on two native <input type=range>.
 * No external deps; thumbs sit on top of a shared track via absolute
 * positioning so it visually reads as one slider. */

function RangeSlider({
  label,
  help,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  help: string;
  min: number;
  max: number;
  step: number;
  value: { min: number; max: number };
  onChange: (v: { min: number; max: number }) => void;
}) {
  const id = useId();
  const range = max - min;
  const lowPct = ((value.min - min) / range) * 100;
  const highPct = ((value.max - min) / range) * 100;
  const fmt = (v: number) =>
    step >= 1 ? v.toFixed(0) : step >= 0.1 ? v.toFixed(1) : v.toFixed(2);

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label
          htmlFor={`${id}-min`}
          className="font-sans text-[12px] text-graphite-soft"
        >
          {label}
        </label>
        <span className="font-sans text-[10px] text-graphite-soft">{help}</span>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="font-mono text-[12px] text-ink tabular-nums">
          {fmt(value.min)}
        </span>
        <span className="font-mono text-[12px] text-ink tabular-nums">
          {fmt(value.max)}
        </span>
      </div>
      <div className="relative mt-2 h-5">
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-lattice" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-ink"
          style={{ left: `${lowPct}%`, right: `${100 - highPct}%` }}
        />
        <input
          id={`${id}-min`}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value.min}
          onChange={(e) => {
            const next = Math.min(parseFloat(e.target.value), value.max);
            onChange({ ...value, min: next });
          }}
          className="dual-thumb pointer-events-none absolute inset-0 h-full w-full appearance-none bg-transparent"
          aria-label={`${label} minimum`}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value.max}
          onChange={(e) => {
            const next = Math.max(parseFloat(e.target.value), value.min);
            onChange({ ...value, max: next });
          }}
          className="dual-thumb pointer-events-none absolute inset-0 h-full w-full appearance-none bg-transparent"
          aria-label={`${label} maximum`}
        />
      </div>
      <style jsx>{`
        .dual-thumb::-webkit-slider-thumb {
          pointer-events: auto;
          appearance: none;
          width: 14px;
          height: 14px;
          border-radius: 9999px;
          background: #14110d;
          border: 2px solid #faf7f1;
          box-shadow: 0 1px 2px rgba(20, 17, 13, 0.2);
          cursor: grab;
        }
        .dual-thumb::-moz-range-thumb {
          pointer-events: auto;
          width: 14px;
          height: 14px;
          border-radius: 9999px;
          background: #14110d;
          border: 2px solid #faf7f1;
          cursor: grab;
        }
      `}</style>
    </div>
  );
}

function ToolChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-lg border px-2.5 py-1 font-sans text-[12px] transition-colors",
        active
          ? "border-ink bg-ink text-paper"
          : "border-lattice bg-paper text-graphite hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}
