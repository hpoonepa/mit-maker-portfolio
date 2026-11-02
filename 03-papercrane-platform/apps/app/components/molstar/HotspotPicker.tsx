"use client";

/**
 * 3D Mol* hotspot picker: full-bleed shell.
 *
 * Layout:
 *   ┌──────────────────────────────┬────────────────┐
 *   │           3D viewer          │ HOTSPOTS rail  │
 *   │       (fills available)      │ chips · legend │
 *   ├──────────────────────────────┴────────────────┤
 *   │ SequencePanel: per-chain letters             │
 *   └───────────────────────────────────────────────┘
 *
 * Selection state lives in the shared HotspotStore so the SequencePanel and
 * the 3D viewport read/write the same Set: bidirectional sync is "free":
 * each path calls `store.add/remove` and the other re-renders.
 *
 * Shortcuts:
 *   h     toggle picking mode
 *   esc   clear selection
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Crosshair, Eraser, Keyboard } from "lucide-react";
import type {
  DesignHighlight,
  SequencePanelChain,
} from "@/components/viewer/types";
import { cn } from "@/lib/utils";
import {
  hotspotKey,
  parseHotspotKey,
  useHotspotStore,
  type HotspotKey,
} from "@/lib/hotspot-store";
import { HotspotChip } from "./HotspotChip";
import { HotspotLegend } from "./HotspotLegend";
import { SequencePanel } from "@/components/targets/SequencePanel";

const StructureLoader = dynamic(
  () =>
    import("@/components/viewer/StructureLoader").then(
      (m) => m.StructureLoader,
    ),
  {
    ssr: false,
    loading: () => <ViewerSkeleton />,
  },
);

const MolstarViewer = dynamic(
  () =>
    import("@/components/viewer/MolstarViewer").then((m) => m.MolstarViewer),
  {
    ssr: false,
    loading: () => <ViewerSkeleton />,
  },
);

export interface HotspotPickerProps {
  /** RCSB PDB id ("5G51"), or a presigned URL if passing `structureUrl`. */
  pdbId?: string;
  /** Direct structure URL: overrides `pdbId`. */
  structureUrl?: string;
  /** Target chain ids: rendered in graphite by the viewer. */
  targetChainIds?: string[];
  /** Maximum hotspots: silently ignores clicks past the cap. */
  max?: number;
  className?: string;
}

export function HotspotPicker({
  pdbId,
  structureUrl,
  targetChainIds,
  max = 20,
  className,
}: HotspotPickerProps) {
  const store = useHotspotStore();
  const [hovered, setHovered] = useState<HotspotKey | null>(null);
  const [chains, setChains] = useState<SequencePanelChain[]>([]);
  // Visible cap-reached toast: auto-clears.
  const [denial, setDenial] = useState<string | null>(null);

  useEffect(() => {
    if (!denial) return;
    const t = setTimeout(() => setDenial(null), 1500);
    return () => clearTimeout(t);
  }, [denial]);

  // Resolve the target chain. Prefer the caller's explicit list; otherwise
  // pick the longest chain so the picker degrades gracefully on PDBs that
  // hand us a non-A target.
  const targetChainId = useMemo(() => {
    if (targetChainIds && targetChainIds[0]) return targetChainIds[0];
    if (chains.length === 0) return "A";
    return chains.reduce((acc, c) =>
      c.residues.length > acc.residues.length ? c : acc,
    ).chainId;
  }, [targetChainIds, chains]);

  // Keyboard shortcuts. Skip when typing in form fields.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "h" || e.key === "H") {
        e.preventDefault();
        store.togglePickingMode();
      } else if (e.key === "Escape") {
        if (store.selection.size > 0) {
          e.preventDefault();
          store.clear();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [store]);

  const sortedKeys = useMemo(
    () =>
      [...store.selection].sort((a, b) => {
        const A = parseHotspotKey(a);
        const B = parseHotspotKey(b);
        if (A.chain !== B.chain) return A.chain.localeCompare(B.chain);
        return A.resi - B.resi;
      }),
    [store.selection],
  );

  // Mol* highlight payload: one entry per selected residue.
  const highlights: DesignHighlight[] = useMemo(
    () =>
      sortedKeys.map((k) => {
        const { chain, resi } = parseHotspotKey(k);
        return {
          chainId: chain,
          resi,
          label: `${chain}:${resi}`,
          style: "sphere" as const,
        };
      }),
    [sortedKeys],
  );

  // Project the selection Set into the SequencePanel shape (resi-only, on
  // the target chain) so the panel can do an O(1) `.has` per letter.
  const selectedOnTarget = useMemo(() => {
    const out = new Set<number>();
    for (const k of store.selection) {
      const { chain, resi } = parseHotspotKey(k);
      if (chain === targetChainId) out.add(resi);
    }
    return out;
  }, [store.selection, targetChainId]);

  const hoveredResi = useMemo(() => {
    if (!hovered) return null;
    const { chain, resi } = parseHotspotKey(hovered);
    return chain === targetChainId ? resi : null;
  }, [hovered, targetChainId]);

  const handleResidueClick = useCallback(
    (id: { chain: string; resi: number }) => {
      if (!store.pickingMode) return;
      if (id.chain !== targetChainId) return;
      if (store.has(id)) {
        store.remove(id);
        return;
      }
      if (store.selection.size >= max) {
        setDenial(`${max} hotspot limit reached`);
        return;
      }
      store.add(id);
    },
    [max, store, targetChainId],
  );

  const handleResidueHover = useCallback(
    (id: { chain: string; resi: number } | null) => {
      setHovered(id && id.chain === targetChainId ? hotspotKey(id) : null);
    },
    [targetChainId],
  );

  // SequencePanel routes through the same store entry points so the 3D and
  // 2D views toggle identical state. Cmd/Ctrl-click is "remove": mirrors
  // the chip rail's X button and the 3D picker's modifier semantics.
  const handleLetterClick = useCallback(
    (chainId: string, resi: number, opts: { remove: boolean }) => {
      if (chainId !== targetChainId) return;
      handleResidueClick({ chain: chainId, resi });
      // `handleResidueClick` already toggles on second click; the explicit
      // remove gesture is here for parity with the chip rail UX even though
      // toggling on existing selection lands on the same code path.
      if (opts.remove && store.has({ chain: chainId, resi })) {
        // No-op: toggle path above already removed it.
      }
    },
    [handleResidueClick, store, targetChainId],
  );

  const handleLetterHover = useCallback(
    (chainId: string, resi: number | null) => {
      if (resi == null) {
        setHovered(null);
        return;
      }
      setHovered(hotspotKey({ chain: chainId, resi }));
    },
    [],
  );

  const handleStructureLoad = useCallback((next: SequencePanelChain[]) => {
    setChains(next);
  }, []);

  return (
    <div
      className={cn(
        "grid grid-rows-[1fr_auto] gap-0",
        // Honours the parent's height when `h-full`/`h-[…]` is supplied
        // (page route gives us `flex-1`); falls back to a viewport-bound
        // minimum so the viewer is never squashed if the parent forgets.
        "min-h-[600px]",
        className,
      )}
    >
      <div className="grid min-h-0 grid-cols-1 gap-0 lg:grid-cols-[1fr_280px]">
        {/* 3D viewer */}
        <div className="relative min-h-0 overflow-hidden">
          {structureUrl ? (
            <MolstarViewer
              structureUrl={structureUrl}
              targetChainIds={targetChainIds}
              highlights={highlights}
              representation="cartoon"
              ariaLabel="3D protein structure: click residues to mark hotspots"
              onResidueClick={handleResidueClick}
              onResidueHover={handleResidueHover}
              onStructureLoad={handleStructureLoad}
            />
          ) : (
            <StructureLoader
              initialPdbId={pdbId}
              enableUpload={false}
              targetChainIds={targetChainIds}
              highlights={highlights}
              onResidueClick={handleResidueClick}
              onResidueHover={handleResidueHover}
              onStructureLoad={handleStructureLoad}
              className="absolute inset-0"
            />
          )}

          {/* Mode badge: top-left, doesn't intercept clicks. */}
          <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border bg-paper/90 px-2.5 py-1 font-mono text-[11px]",
                store.pickingMode
                  ? "border-crane-deep text-crane-deep"
                  : "border-lattice-strong text-graphite",
              )}
              aria-live="polite"
            >
              <Crosshair className="h-3 w-3" />
              {store.pickingMode ? "Picking" : "View only"}
            </span>
            <span
              className="hidden items-center gap-1.5 rounded-full border border-lattice-strong bg-paper/90 px-2.5 py-1 font-mono text-[11px] text-graphite-soft md:inline-flex"
              title="Press h to toggle picking, Esc to clear"
            >
              <Keyboard className="h-3 w-3" />
              h · Esc
            </span>
          </div>

          {denial && (
            <div
              role="status"
              aria-live="assertive"
              className="absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-crane px-4 py-1.5 font-sans text-[12px] text-paper"
            >
              {denial}
            </div>
          )}
        </div>

        {/* HOTSPOTS sidebar */}
        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto bg-paper-fold/30 px-4 py-3">
          <div className="flex items-baseline justify-between">
            <span className="font-sans text-[12px] text-graphite-soft">
              Hotspots
            </span>
            <span className="font-mono text-[11px] tabular-nums text-ink">
              {sortedKeys.length}/{max}
            </span>
          </div>

          <div
            role="list"
            aria-label="Selected hotspots"
            className="flex min-h-[60px] flex-wrap items-start gap-2 bg-paper/60 px-3 py-2"
          >
            {sortedKeys.length === 0 ? (
              <span className="font-sans text-[12px] text-graphite-soft">
                Click a residue or letter to add.
              </span>
            ) : (
              sortedKeys.map((k, i) => {
                const { chain, resi } = parseHotspotKey(k);
                const n = sortedKeys.length;
                const strength = n <= 1 ? 0.5 : i / (n - 1);
                return (
                  <HotspotChip
                    key={k}
                    chain={chain}
                    resi={resi}
                    strength={strength}
                    active={hovered === k}
                    onRemove={() => store.remove({ chain, resi })}
                  />
                );
              })
            )}
          </div>

          {sortedKeys.length > 0 && (
            <button
              type="button"
              onClick={() => store.clear()}
              className="inline-flex items-center justify-center gap-1 self-start rounded-full border border-lattice-strong bg-paper px-3 py-1.5 font-mono text-[11px] text-ink transition-colors hover:border-ink"
              title="Clear all (Esc)"
            >
              <Eraser className="h-3 w-3" />
              Clear all
            </button>
          )}

          <HotspotLegend
            showGradient={sortedKeys.length > 1}
            count={sortedKeys.length}
          />

          <p className="px-1 font-sans text-[11px] leading-relaxed text-graphite-soft">
            Click a residue or letter to add.{" "}
            <span className="font-mono">⌘/Ctrl-click</span> removes it. Press{" "}
            <span className="font-mono">h</span> to toggle picking,{" "}
            <span className="font-mono">Esc</span> to clear.
          </p>
        </aside>
      </div>

      {/* SequencePanel */}
      <SequencePanel
        chains={chains}
        selected={selectedOnTarget}
        hoveredResi={hoveredResi}
        targetChainId={targetChainId}
        onLetterClick={handleLetterClick}
        onLetterHover={handleLetterHover}
      />
    </div>
  );
}

function ViewerSkeleton() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full w-full items-center justify-center bg-paper-fold/40"
    >
      <div className="flex flex-col items-center gap-3">
        <div className="h-12 w-12 animate-pulse rounded-full border-2 border-crane-deep/30 border-t-crane-deep" />
        <span className="font-sans text-[12px] text-graphite-soft">
          Loading 3D viewer…
        </span>
      </div>
    </div>
  );
}

export default HotspotPicker;
