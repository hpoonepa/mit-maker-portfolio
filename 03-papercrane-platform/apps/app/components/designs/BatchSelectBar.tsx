"use client";

/**
 * BatchSelectBar: sticky footer that appears once the user has selected
 * one or more designs in the gallery. Hosts the Export menu plus a Cancel
 * button that clears the selection.
 *
 * Selection is owned by the parent (DesignsGallery) so we just render a
 * thin presentation layer here.
 */

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { DesignExport, type ExportableDesign } from "./DesignExport";

const BATCH_LIMIT = 500;

export interface BatchSelectBarProps {
  selected: ExportableDesign[];
  onClear: () => void;
  archiveName?: string;
}

export function BatchSelectBar({
  selected,
  onClear,
  archiveName,
}: BatchSelectBarProps) {
  const [toast, setToast] = useState<string | null>(null);
  const [warnLimit, setWarnLimit] = useState(false);

  useEffect(() => {
    if (selected.length > BATCH_LIMIT) setWarnLimit(true);
  }, [selected.length]);

  // Auto-clear toast after a short delay so it doesn't pile up.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  if (selected.length === 0) return null;

  const exportable = selected.slice(0, BATCH_LIMIT);

  return (
    <>
      <div
        role="toolbar"
        aria-label="Batch design actions"
        className={cn(
          "fixed inset-x-0 bottom-0 z-40 border-t border-lattice-strong",
          "bg-paper/95",
        )}
      >
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <span className="font-display text-[15px] text-ink tabular-nums">
            {selected.length}
          </span>
          <span className="font-sans text-[12px] text-graphite">
            selected
          </span>
          {selected.length > BATCH_LIMIT && (
            <span className="font-sans text-[12px] text-crane-deep">
              · capped at {BATCH_LIMIT}
            </span>
          )}

          {toast && (
            <span className="ml-3 truncate font-sans text-[12px] text-graphite">
              {toast}
            </span>
          )}

          <div className="ml-auto flex items-center gap-2">
            <DesignExport
              designs={exportable}
              archiveName={archiveName}
              onProgress={setToast}
              variant="solid"
            />
            <button
              type="button"
              onClick={onClear}
              className={cn(
                "inline-flex items-center gap-1 rounded-xl border border-lattice px-3 py-1.5",
                "font-sans text-[12px] text-graphite",
                "transition-colors hover:border-lattice-strong hover:text-ink",
              )}
            >
              <X className="h-3 w-3" />
              Cancel
            </button>
          </div>
        </div>
      </div>

      {warnLimit && (
        <BatchLimitDialog
          count={selected.length}
          limit={BATCH_LIMIT}
          onClose={() => setWarnLimit(false)}
        />
      )}
    </>
  );
}

function BatchLimitDialog({
  count,
  limit,
  onClose,
}: {
  count: number;
  limit: number;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="batch-limit-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
      onClick={onClose}
    >
      <div
        className="max-w-md bg-paper p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="batch-limit-title"
          className="font-display text-[18px] text-ink"
        >
          Selection capped at {limit}
        </h2>
        <p className="mt-2 font-sans text-[13px] text-graphite">
          You selected {count.toLocaleString()} designs, but exports are limited
          to {limit} at a time to keep things responsive. The first {limit} will
          be included; deselect some to choose which ones.
        </p>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-ink bg-ink px-4 py-1.5 font-sans text-[12px] text-paper hover:bg-ink/90"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
