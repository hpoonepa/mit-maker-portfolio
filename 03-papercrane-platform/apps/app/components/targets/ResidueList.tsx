"use client";

import { X, Flame } from "lucide-react";
import type { ResidueEntry } from "@/lib/pdb/parse";

export type ResidueListProps = {
  /** Currently selected residues, in author-seq order. */
  selected: ResidueEntry[];
  /** Remove a single hotspot. */
  onRemove: (authSeqId: number) => void;
  /** Clear all: only shown when at least one is selected. */
  onClear: () => void;
  /** Practical limit for design tools (RFdiffusion / BindCraft). */
  max?: number;
};

/**
 * Sidebar list of currently selected hotspot residues. Paired with the
 * HotspotPicker in a two-column layout; this one is the authoritative view.
 */
export function ResidueList({
  selected,
  onRemove,
  onClear,
  max = 20,
}: ResidueListProps) {
  const count = selected.length;
  const nearLimit = count >= max - 2;

  return (
    <div className="flex flex-col overflow-hidden">
      <div className="px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 font-sans text-[12px] text-graphite-soft">
              <Flame className="w-3.5 h-3.5" />
              Selected hotspots
            </div>
            <div className="mt-0.5 font-display text-[22px] text-ink">
              {count}
              <span className="ml-1 font-mono text-[12px] text-graphite-soft">
                / {max}
              </span>
            </div>
          </div>
          {count > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="font-sans text-[12px] text-graphite transition-colors hover:text-crane-deep"
            >
              Clear all
            </button>
          )}
        </div>
        <div
          className="mt-3 h-1 overflow-hidden rounded-full bg-lattice"
          role="progressbar"
          aria-label={`${count} of ${max} hotspots selected`}
          aria-valuemin={0}
          aria-valuemax={max}
          aria-valuenow={count}
        >
          <div
            className="h-full rounded-full bg-crane-red transition-[width] duration-300"
            style={{ width: `${Math.min(100, (count / max) * 100)}%` }}
          />
        </div>
      </div>

      {count === 0 ? (
        <div className="flex min-h-52 flex-col items-center justify-center px-6 py-8 text-center">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-lattice bg-paper text-crane-deep">
            <Flame className="h-4 w-4" aria-hidden />
          </span>
          <p className="mt-3 font-display text-[17px] text-ink">
            No hotspots yet
          </p>
          <p className="mt-1 max-w-48 font-sans text-[12px] leading-relaxed text-graphite">
            Pick residues in the 3D structure or sequence view to build the
            interface.
          </p>
        </div>
      ) : (
        <ul className="max-h-[390px] overflow-y-auto py-2 xl:max-h-[430px]">
          {selected.map((res) => (
            <li key={`${res.authSeqId}${res.insCode}`}>
              <div className="group flex items-center justify-between px-4 py-2 transition-colors hover:bg-paper/70">
                <div className="flex items-center gap-3">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-crane-glow font-mono text-[12px] text-crane-deep">
                    {res.oneLetter}
                  </span>
                  <div className="flex flex-col leading-tight">
                    <span className="font-mono text-[13px] text-ink">
                      {res.resName}
                      <span className="text-graphite-soft">
                        {" "}
                        {res.authSeqId}
                        {res.insCode}
                      </span>
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(res.authSeqId)}
                  className="rounded-md p-1.5 text-graphite-soft opacity-60 transition-all hover:bg-paper hover:text-crane-deep hover:opacity-100 group-hover:opacity-100 focus:opacity-100"
                  aria-label={`Remove ${res.resName} ${res.authSeqId}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {nearLimit && count < max && (
        <div className="px-5 py-3 font-sans text-[12px] text-graphite">
          You're nearing the {max}-hotspot cap. Most design tools plateau here.
        </div>
      )}
      {count >= max && (
        <div className="bg-crane-glow px-5 py-3 font-sans text-[12px] text-crane-deep">
          {max} hotspots max: remove one to pick a different residue.
        </div>
      )}
    </div>
  );
}
