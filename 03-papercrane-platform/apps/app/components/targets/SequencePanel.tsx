"use client";

/**
 * Paper-themed sequence strip that mirrors selection and hover state with the
 * 3D viewport. Target chain renders interactive letters (click to toggle a
 * hotspot, hover to highlight in 3D); non-target chains are dimmed.
 *
 * Bidirectional sync is shared-state, not event-bus: the parent owns
 * `selected` + `hoveredResi`, and the same setters are wired into both the
 * 3D click/hover path and this panel. Clicking either side toggles the same
 * Set, so the visual cue propagates automatically on the next render.
 */
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { SequencePanelChain } from "@/components/viewer/types";

export interface SequencePanelProps {
  chains: SequencePanelChain[];
  /** Hotspots picked, by residue number on the target chain. */
  selected: Set<number>;
  /** Mirrors the 3D hover so the panel underlines the same residue. */
  hoveredResi: number | null;
  /** Chain id the hotspots apply to: only this chain is clickable. */
  targetChainId: string;
  /** Click semantics: defer to parent (Cmd/Ctrl-click handled inside). */
  onLetterClick: (
    chainId: string,
    resi: number,
    opts: { remove: boolean },
  ) => void;
  onLetterHover: (chainId: string, resi: number | null) => void;
  className?: string;
}

export function SequencePanel({
  chains,
  selected,
  hoveredResi,
  targetChainId,
  onLetterClick,
  onLetterHover,
  className,
}: SequencePanelProps) {
  if (!chains || chains.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center border-t border-lattice bg-paper-fold/40 px-6 py-3 font-sans text-[12px] text-graphite-soft",
          className,
        )}
      >
        Sequence will appear when a structure is loaded
      </div>
    );
  }

  return (
    <div
      className={cn(
        "border-t border-lattice bg-paper-fold/30",
        className,
      )}
      aria-label="Target sequence"
    >
      <div className="flex max-h-[28vh] flex-col gap-2 overflow-y-auto px-4 py-3">
        {chains.map((chain) => (
          <ChainRow
            key={chain.chainId}
            chain={chain}
            isTarget={chain.chainId === targetChainId}
            selected={selected}
            hoveredResi={hoveredResi}
            onLetterClick={onLetterClick}
            onLetterHover={onLetterHover}
          />
        ))}
      </div>
    </div>
  );
}

interface ChainRowProps {
  chain: SequencePanelChain;
  isTarget: boolean;
  selected: Set<number>;
  hoveredResi: number | null;
  onLetterClick: SequencePanelProps["onLetterClick"];
  onLetterHover: SequencePanelProps["onLetterHover"];
}

/**
 * One row per chain. The target chain scrolls horizontally so each residue
 * keeps a stable position you can scrub through; other chains wrap so they
 * don't dominate vertical space.
 */
function ChainRow({
  chain,
  isTarget,
  selected,
  hoveredResi,
  onLetterClick,
  onLetterHover,
}: ChainRowProps) {
  // Tick every 10 for short chains, every 50 for long ones (>= 300 residues)
  //: keeps the rule readable without crowding letters.
  const tickEvery = chain.residues.length >= 300 ? 50 : 10;

  const ticks = useMemo(() => {
    const out: Array<{ idx: number; resi: number }> = [];
    for (let i = 0; i < chain.residues.length; i++) {
      const r = chain.residues[i];
      if (!r) continue;
      if (i === 0 || (i + 1) % tickEvery === 0) {
        out.push({ idx: i, resi: r.resi });
      }
    }
    return out;
  }, [chain.residues, tickEvery]);

  return (
    <div className="flex items-start gap-3">
      <div className="flex w-16 shrink-0 flex-col gap-0.5 pt-2">
        <span className="font-sans text-[12px] text-graphite-soft">
          Chain
        </span>
        <span
          className={cn(
            "font-display text-[15px] leading-none",
            isTarget ? "text-ink" : "text-graphite-soft",
          )}
        >
          {chain.chainId}
        </span>
        <span className="font-mono text-[10px] tabular-nums text-graphite-soft">
          {chain.residues.length}
        </span>
      </div>

      <div
        className={cn(
          "min-w-0 flex-1",
          isTarget ? "overflow-x-auto" : "",
          !isTarget && "opacity-40",
        )}
      >
        {/* Tick row */}
        <div
          className={cn(
            "flex font-mono text-[9px] tabular-nums text-graphite-soft",
            isTarget ? "whitespace-nowrap" : "flex-wrap",
          )}
          aria-hidden="true"
          style={{ minHeight: "12px" }}
        >
          {chain.residues.map((r, i) => {
            const tick = ticks.find((t) => t.idx === i);
            return (
              <span
                key={`tick-${i}`}
                className="inline-block w-[12px] text-center"
                style={{ minWidth: "12px" }}
              >
                {tick ? tick.resi : ""}
              </span>
            );
          })}
        </div>

        {/* Letter row */}
        <div
          className={cn(
            "flex font-mono text-[13px] leading-none",
            isTarget ? "whitespace-nowrap" : "flex-wrap",
          )}
          role="group"
          aria-label={`Chain ${chain.chainId} sequence`}
        >
          {chain.residues.map((r) => {
            const isSel = isTarget && selected.has(r.resi);
            const isHov = isTarget && hoveredResi === r.resi;
            return (
              <button
                key={`${chain.chainId}-${r.resi}`}
                type="button"
                disabled={!isTarget}
                onClick={(e) =>
                  isTarget &&
                  onLetterClick(chain.chainId, r.resi, {
                    remove: e.metaKey || e.ctrlKey,
                  })
                }
                onMouseEnter={() =>
                  isTarget && onLetterHover(chain.chainId, r.resi)
                }
                onMouseLeave={() => isTarget && onLetterHover(chain.chainId, null)}
                className={cn(
                  "inline-flex h-[18px] w-[12px] items-center justify-center transition-colors",
                  isTarget
                    ? "cursor-pointer text-ink hover:bg-paper-fold"
                    : "cursor-default text-graphite",
                  isSel && "bg-crane text-paper hover:bg-crane-deep",
                  !isSel && isHov && "ring-1 ring-ink-soft",
                )}
                title={
                  isTarget
                    ? `${chain.chainId}:${r.resi} · ${r.aa3}${isSel ? " · selected" : ""}`
                    : `${chain.chainId}:${r.resi} · ${r.aa3} (non-target)`
                }
                aria-label={`Residue ${chain.chainId}:${r.resi} ${r.aa3}`}
                aria-pressed={isSel || undefined}
              >
                {r.aa}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default SequencePanel;
