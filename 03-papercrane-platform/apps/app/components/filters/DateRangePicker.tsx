"use client";

import { Calendar } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DatePreset, DateRange } from "@/lib/hooks/useFilters";

export interface DateRangePickerProps {
  label?: string;
  value: DateRange;
  onChange: (next: DateRange) => void;
  className?: string;
}

const PRESETS: { id: DatePreset; label: string }[] = [
  { id: "all", label: "All time" },
  { id: "24h", label: "Last 24h" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "custom", label: "Custom" },
];

/**
 * Compact date-range picker with quick presets and an optional custom
 * mode that exposes two native date inputs.
 */
export function DateRangePicker({
  label = "Date",
  value,
  onChange,
  className,
}: DateRangePickerProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center gap-1.5 font-sans text-[12px] text-graphite-soft">
        <Calendar className="h-3 w-3" />
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => {
          const active = value.preset === p.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() =>
                onChange({
                  preset: p.id,
                  from: p.id === "custom" ? value.from : null,
                  to: p.id === "custom" ? value.to : null,
                })
              }
              className={cn(
                "rounded-full border px-3 py-1 font-sans text-[12px] transition-colors",
                active
                  ? "border-ink bg-ink text-paper"
                  : "border-lattice bg-paper-fold/40 text-graphite hover:text-ink hover:border-lattice-strong",
              )}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      {value.preset === "custom" && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <input
            type="date"
            aria-label="From date"
            value={value.from ?? ""}
            onChange={(e) =>
              onChange({ ...value, from: e.target.value || null })
            }
            className="rounded-lg border border-lattice bg-paper px-2.5 py-1 font-mono text-[12px] text-ink focus:outline-none focus:border-ink"
          />
          <span className="font-sans text-[12px] text-graphite-soft">to</span>
          <input
            type="date"
            aria-label="To date"
            value={value.to ?? ""}
            onChange={(e) => onChange({ ...value, to: e.target.value || null })}
            className="rounded-lg border border-lattice bg-paper px-2.5 py-1 font-mono text-[12px] text-ink focus:outline-none focus:border-ink"
          />
        </div>
      )}
    </div>
  );
}

/** Resolve a DateRange into concrete ISO bounds for filtering. */
export function resolveDateRange(
  range: DateRange,
  now: Date = new Date(),
): { from: Date | null; to: Date | null } {
  switch (range.preset) {
    case "24h":
      return { from: new Date(now.getTime() - 24 * 60 * 60 * 1000), to: now };
    case "7d":
      return {
        from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000),
        to: now,
      };
    case "30d":
      return {
        from: new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000),
        to: now,
      };
    case "custom":
      return {
        from: range.from ? new Date(range.from) : null,
        to: range.to ? new Date(range.to) : null,
      };
    default:
      return { from: null, to: null };
  }
}
