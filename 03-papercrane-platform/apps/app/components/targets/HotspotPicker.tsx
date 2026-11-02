"use client";

import { useMemo, useState } from "react";
import { Copy, Check, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChainEntry, ResidueEntry } from "@/lib/pdb/parse";

export type HotspotPickerProps = {
  chain: ChainEntry;
  /** Author-seq ids (PDB numbering) currently selected as hotspots. */
  selected: Set<number>;
  onChange: (next: Set<number>) => void;
  /** Cap on selections; the picker enforces this silently. */
  max?: number;
};

const ROW_SIZE = 50;

/**
 * 2D sequence view for picking hotspots. Residues are rendered in 10-residue
 * groups across 50-residue rows, matching how biochemists eyeball sequences
 * in UniProt / BLAST outputs.
 *
 * Selection toggles on click; selected residues get a crane-glow background
 * and a crane-deep border. Deselect is one more click.
 */
export function HotspotPicker({
  chain,
  selected,
  onChange,
  max = 20,
}: HotspotPickerProps) {
  const [copied, setCopied] = useState(false);

  const rows = useMemo(() => chunk(chain.residues, ROW_SIZE), [chain.residues]);
  const selectedIds = useMemo(
    () => [...selected].sort((a, b) => a - b),
    [selected],
  );

  const toggle = (authSeqId: number) => {
    const next = new Set(selected);
    if (next.has(authSeqId)) {
      next.delete(authSeqId);
    } else {
      if (next.size >= max) return;
      next.add(authSeqId);
    }
    onChange(next);
  };

  const copyPositions = async () => {
    const text = selectedIds.join(",");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Fallback: select a hidden textarea. On modern browsers the first
      // path works everywhere under an https/localhost origin; we just
      // swallow the error to avoid a noisy toast.
    }
  };

  const atCap = selected.size >= max;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-sans text-[13px] text-graphite">
          <Info className="w-3.5 h-3.5" />
          Click residues to toggle hotspots. Chain {chain.id},{" "}
          {chain.residues.length} residues.
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={copyPositions}
            disabled={selected.size === 0}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[12px] transition-colors",
              "border-lattice-strong bg-paper text-ink hover:border-ink disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-lattice-strong",
            )}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5" />
                Copied
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                Copy positions
              </>
            )}
          </button>
        </div>
      </div>

      <div
        role="grid"
        aria-label={`Residue picker for chain ${chain.id}`}
        className="bg-paper p-5 font-mono text-[14px] leading-snug overflow-x-auto"
      >
        {rows.map((row, rowIdx) => {
          const rowStart = row[0]?.authSeqId ?? 0;
          return (
            <div
              key={rowIdx}
              role="row"
              className="flex items-center gap-3 py-1"
            >
              <span
                aria-hidden
                className="w-12 shrink-0 text-right text-[11px] text-graphite-soft"
              >
                {rowStart}
              </span>
              <div className="flex flex-wrap gap-x-[2px] gap-y-0.5">
                {row.map((res, colIdx) => {
                  const isSelected = selected.has(res.authSeqId);
                  // Insert a spacer every 10 residues: classic seq formatting.
                  const gapBefore = colIdx > 0 && colIdx % 10 === 0;
                  const disabled = !isSelected && atCap;
                  return (
                    <span
                      key={`${res.authSeqId}${res.insCode}`}
                      className={cn("inline-flex", gapBefore && "ml-2")}
                    >
                      <button
                        type="button"
                        role="gridcell"
                        aria-selected={isSelected}
                        aria-label={`${res.resName} ${res.authSeqId}${res.insCode}`}
                        disabled={disabled}
                        onClick={() => toggle(res.authSeqId)}
                        title={`${res.resName} ${res.authSeqId}${res.insCode}`}
                        className={cn(
                          "w-5 h-6 rounded-[5px] text-center transition-colors select-none",
                          isSelected
                            ? "bg-crane-glow text-crane-deep ring-1 ring-crane-deep"
                            : "text-ink hover:bg-paper-fold",
                          disabled && "opacity-40 cursor-not-allowed hover:bg-transparent",
                        )}
                      >
                        {res.oneLetter}
                      </button>
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {selected.size > 0 && (
        <div className="px-4 py-3">
          <p className="font-sans text-[12px] text-graphite-soft">
            Selected positions
          </p>
          <p className="mt-1 break-all font-mono text-[13px] text-ink">
            {selectedIds.join(",")}
          </p>
        </div>
      )}
    </div>
  );
}

function chunk<T>(arr: T[], size: number): T[][] {
  if (size <= 0) return [arr];
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

/**
 * Helper for callers: derive the ResidueEntry[] (in author-seq order) for a
 * given selection set. Exported so `ResidueList` can render the sidebar
 * without recomputing the map itself.
 */
export function resolveSelected(
  chain: ChainEntry,
  selected: Set<number>,
): ResidueEntry[] {
  return chain.residues.filter((r) => selected.has(r.authSeqId));
}
