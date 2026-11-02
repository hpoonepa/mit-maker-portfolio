"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChipOption {
  id: string;
  label: string;
  count?: number;
}

export interface MultiSelectChipsProps {
  label: string;
  options: ChipOption[];
  value: string[];
  onChange: (next: string[]) => void;
  className?: string;
  /** Render in a single horizontal row instead of wrapping. */
  inline?: boolean;
}

/**
 * Chip-style multi-select. Click toggles inclusion. Designed for short
 * lists like job statuses or tool ids.
 */
export function MultiSelectChips({
  label,
  options,
  value,
  onChange,
  className,
  inline,
}: MultiSelectChipsProps) {
  const toggle = (id: string) => {
    if (value.includes(id)) onChange(value.filter((x) => x !== id));
    else onChange([...value, id]);
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="font-sans text-[12px] text-graphite-soft">
        {label}
      </div>
      <div
        className={cn(
          "flex gap-1.5",
          inline ? "flex-nowrap overflow-x-auto" : "flex-wrap",
        )}
        role="group"
        aria-label={label}
      >
        {options.map((opt) => {
          const active = value.includes(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              role="checkbox"
              aria-checked={active}
              onClick={() => toggle(opt.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-sans text-[12px] transition-colors whitespace-nowrap",
                active
                  ? "border-ink bg-ink text-paper"
                  : "border-lattice bg-paper-fold/40 text-graphite hover:text-ink hover:border-lattice-strong",
              )}
            >
              {active && <Check className="h-3 w-3" />}
              {opt.label}
              {typeof opt.count === "number" && (
                <span
                  className={cn(
                    "font-mono text-[10px] tabular-nums",
                    active ? "text-paper/70" : "text-graphite-soft",
                  )}
                >
                  {opt.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
