"use client";

import { useId } from "react";
import {
  Check,
  Gauge,
  SlidersHorizontal,
  SplitSquareHorizontal,
  type LucideIcon,
} from "lucide-react";
import type { AllocationStrategy } from "@/lib/jobs/allocation";
import { manualSumValid } from "@/lib/jobs/allocation";
import { cn } from "@/lib/utils";

export interface AllocationControlProps {
  toolIds: string[];
  toolNames: Record<string, string>;
  totalDesigns: number;
  strategy: AllocationStrategy;
  onStrategyChange: (s: AllocationStrategy) => void;
  manualCounts: Record<string, number>;
  onManualChange: (toolId: string, value: number) => void;
  /** Computed by the parent via allocate(); display only: never recomputed here. */
  perToolCounts: Record<string, number>;
}

type StrategyMeta = {
  id: AllocationStrategy;
  label: string;
  subtext: string;
  icon: LucideIcon;
  recommended?: boolean;
};

const STRATEGIES: StrategyMeta[] = [
  {
    id: "auto",
    label: "Auto",
    subtext: "Let Papercrane split the runs",
    icon: Gauge,
    recommended: true,
  },
  {
    id: "even",
    label: "Even",
    subtext: "Split equally across every tool",
    icon: SplitSquareHorizontal,
  },
  {
    id: "manual",
    label: "Manual",
    subtext: "Set each tool's count manually",
    icon: SlidersHorizontal,
  },
];

/**
 * Strategy picker + (in manual mode) per-tool count editor for splitting a
 * total design budget across 2+ tools. Purely presentational: the parent owns
 * the strategy, the manual counts, and the computed `perToolCounts` (via
 * `allocate()`). This component never runs the allocation math itself.
 *
 * Only rendered by the parent when `toolIds.length >= 2`.
 */
export function AllocationControl({
  toolIds,
  toolNames,
  totalDesigns,
  strategy,
  onStrategyChange,
  manualCounts,
  onManualChange,
  perToolCounts,
}: AllocationControlProps): JSX.Element {
  const groupId = useId();

  const manualTotal = toolIds.reduce(
    (acc, id) => acc + (manualCounts[id] ?? 0),
    0,
  );
  const remaining = totalDesigns - manualTotal;
  const manualValid = manualSumValid(manualCounts, toolIds, totalDesigns);

  const nameOf = (id: string) => toolNames[id] ?? id;

  return (
    <div className="space-y-5" data-testid="e2e-allocation-control">
      <div className="space-y-1">
        <p className="font-sans text-[12px] text-graphite-soft">
          Allocation strategy
        </p>
        <p className="font-sans text-[13px] text-graphite">
          Choose how {totalDesigns.toLocaleString("en-US")} designs get split
          across your {toolIds.length} tools.
        </p>
      </div>

      {/* Strategy cards */}
      <div
        role="radiogroup"
        aria-label="Allocation strategy"
        className="grid grid-cols-1 gap-3 sm:grid-cols-3"
      >
        {STRATEGIES.map((s) => {
          const selected = strategy === s.id;
          const Icon = s.icon;
          return (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={selected}
              data-testid={`e2e-allocation-strategy-${s.id}`}
              onClick={() => onStrategyChange(s.id)}
              className={cn(
                "group relative flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
                selected
                  ? "border-crane bg-paper"
                  : "border-lattice bg-paper hover:border-lattice-strong",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-md border transition-colors",
                    selected
                      ? "border-crane-deep/40 bg-crane text-paper"
                      : "border-lattice-strong bg-paper-fold text-graphite",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                {selected ? (
                  <Check
                    className="h-4 w-4 text-crane-deep"
                    aria-hidden="true"
                  />
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "font-display text-[15px] tracking-tight",
                    selected ? "text-ink" : "text-graphite",
                  )}
                >
                  {s.label}
                </span>
                {s.recommended ? (
                  <span className="rounded-full border border-crane-deep/30 bg-crane/10 px-2 py-0.5 font-sans text-[12px] text-crane-deep">
                    recommended
                  </span>
                ) : null}
              </div>
              <p className="font-sans text-[12px] leading-snug text-graphite-soft">
                {s.subtext}
              </p>
            </button>
          );
        })}
      </div>

      {/* Per-tool breakdown */}
      <div className="space-y-2 p-4">
        {strategy === "manual" ? (
          <div className="flex items-baseline justify-between">
            <p className="font-sans text-[12px] text-graphite-soft">
              Designs per tool
            </p>
            <p
              role="status"
              className={cn(
                "font-mono text-[12px] tabular-nums",
                remaining === 0
                  ? "text-graphite"
                  : remaining < 0
                    ? "text-crane-deep"
                    : "text-ink",
              )}
            >
              remaining: {remaining.toLocaleString("en-US")}
            </p>
          </div>
        ) : (
          <p className="font-sans text-[12px] text-graphite-soft">
            Designs per tool
          </p>
        )}

        <ul className="divide-y divide-lattice">
          {toolIds.map((id, index) => {
            const count = perToolCounts[id] ?? 0;
            const inputId = `${groupId}-${index}`;
            const manualVal = manualCounts[id] ?? 0;
            return (
              <li
                key={id}
                className="flex items-center justify-between gap-4 py-2.5 first:pt-0 last:pb-0"
              >
                <label
                  htmlFor={strategy === "manual" ? inputId : undefined}
                  className="min-w-0 flex-1 truncate font-sans text-[14px] text-ink"
                >
                  {nameOf(id)}
                </label>

                {strategy === "manual" ? (
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0}
                      max={totalDesigns}
                      step={1}
                      value={manualVal}
                      aria-label={`${nameOf(id)} designs`}
                      onChange={(e) =>
                        onManualChange(
                          id,
                          clampInt(e.target.value, 0, totalDesigns),
                        )
                      }
                      className={cn(
                        "hidden h-1.5 w-28 cursor-pointer appearance-none rounded-full accent-ink sm:block",
                        "bg-lattice-strong",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
                      )}
                    />
                    <input
                      id={inputId}
                      type="number"
                      min={0}
                      max={totalDesigns}
                      step={1}
                      value={manualVal}
                      data-testid={`e2e-allocation-input-${id}`}
                      onChange={(e) =>
                        onManualChange(
                          id,
                          clampInt(e.target.value, 0, totalDesigns),
                        )
                      }
                      className={cn(
                        "w-20 rounded-xl border bg-paper px-3 py-1.5 text-right font-mono text-[14px] tabular-nums text-ink",
                        "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink",
                        manualValid ? "border-lattice-strong" : "border-crane",
                      )}
                    />
                  </div>
                ) : (
                  <span
                    data-testid={`e2e-allocation-count-${id}`}
                    className="font-mono text-[14px] tabular-nums text-ink"
                  >
                    {count.toLocaleString("en-US")}
                  </span>
                )}
              </li>
            );
          })}
        </ul>

        {strategy === "manual" && !manualValid ? (
          <p role="alert" className="font-sans text-[12px] text-crane-deep">
            {remaining > 0
              ? `Allocate ${remaining.toLocaleString("en-US")} more design${
                  remaining === 1 ? "" : "s"
                } to match the total.`
              : `Remove ${Math.abs(remaining).toLocaleString("en-US")} design${
                  Math.abs(remaining) === 1 ? "" : "s"
                }: over the total by that much.`}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function clampInt(raw: string, min: number, max: number): number {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, Math.floor(n)));
}
