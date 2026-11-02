"use client";

import { useEffect, useState } from "react";
import { Search, X, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/hooks/useFilters";
import { SavedViews } from "./SavedViews";

export interface FilterBarProps<T> {
  /** Search input current value (controlled by parent: usually URL state). */
  search: string;
  /** Called with the debounced search value. */
  onSearchChange: (next: string) => void;
  searchPlaceholder?: string;
  /** Toggle the advanced filter panel render. */
  panelOpen?: boolean;
  onTogglePanel?: () => void;
  /** Number of active (non-default) filter constraints. */
  activeCount?: number;
  /** "12 of 84" style helper text. */
  resultsLabel?: string;
  /** Saved views integration. */
  savedViews?: {
    pageKey: string;
    userId?: string;
    current: T;
    onApply: (state: T) => void;
    canSave?: boolean;
  };
  onReset?: () => void;
  className?: string;
  children?: React.ReactNode;
}

/**
 * Composable filter bar: search input + chip slot + advanced panel
 * toggle + saved views. Children render inside the expandable panel.
 */
export function FilterBar<T>({
  search,
  onSearchChange,
  searchPlaceholder = "Search…",
  panelOpen,
  onTogglePanel,
  activeCount = 0,
  resultsLabel,
  savedViews,
  onReset,
  className,
  children,
}: FilterBarProps<T>) {
  const [localSearch, setLocalSearch] = useState(search);
  const debounced = useDebouncedValue(localSearch, 200);

  // Sync local → upstream when debounced value changes.
  useEffect(() => {
    if (debounced !== search) onSearchChange(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  // Sync upstream → local when URL changes externally (e.g. saved view applied).
  useEffect(() => {
    if (search !== localSearch && search !== debounced) {
      setLocalSearch(search);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-60">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-graphite-soft" />
          <input
            type="search"
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="w-full rounded-lg border-0 bg-paper-fold/60 py-3 pl-9 pr-9 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus-visible:outline-crane"
          />
          {localSearch && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setLocalSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-graphite-soft hover:text-ink"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {onTogglePanel && (
          <button
            type="button"
            onClick={onTogglePanel}
            aria-expanded={panelOpen}
            className={cn(
              "inline-flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 font-sans text-[13px] transition-colors",
              panelOpen
                ? "bg-paper-fold text-crane"
                : "text-graphite hover:text-ink",
            )}
          >
            <SlidersHorizontal className="h-3 w-3" />
            Filters
            {activeCount > 0 && (
              <span
                className={cn(
                  "rounded-full px-1.5 font-mono text-[10px] tabular-nums",
                  panelOpen
                    ? "bg-paper text-ink"
                    : "bg-ink text-paper",
                )}
              >
                {activeCount}
              </span>
            )}
          </button>
        )}

        {savedViews && (
          <SavedViews<T>
            pageKey={savedViews.pageKey}
            userId={savedViews.userId}
            current={savedViews.current}
            onApply={savedViews.onApply}
            canSave={savedViews.canSave}
          />
        )}

        {resultsLabel && (
          <span className="ml-auto font-sans text-[12px] text-graphite-soft tabular-nums">
            {resultsLabel}
          </span>
        )}

        {onReset && activeCount > 0 && (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-1 rounded-xl border border-lattice bg-paper-fold/60 px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink hover:border-lattice-strong transition-colors"
          >
            <X className="h-3 w-3" />
            Reset
          </button>
        )}
      </div>

      {panelOpen && children && (
        <div className="py-5">
          {children}
        </div>
      )}
    </div>
  );
}
