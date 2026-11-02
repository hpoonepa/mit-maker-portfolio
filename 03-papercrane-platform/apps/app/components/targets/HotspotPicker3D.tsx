"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Focus, Info, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  DesignHighlight,
  StructureFormat,
} from "@/components/viewer/types";
import { looksLikeCif } from "@/lib/pdb/parse";
import {
  buildHotspotHighlights,
  clampSelectionToggle,
  nextFocusResidue,
} from "@/lib/viewer/residueSelection";

/*
 * 3D hotspot picker. Wraps `MolstarViewer` with click-to-toggle behaviour so
 * users can pick hotspots by looking at the structure instead of scanning
 * the 2D sequence grid. Selection state is controlled by the parent so the
 * 2D and 3D pickers stay in sync (see `HotspotPickerTabs`).
 *
 * Interaction model
 * -----------------
 *  - Click a residue on the target chain   → toggle in the selection Set.
 *  - Click a residue on another target chain → ignored (only the active chain is editable).
 *  - Click when already at cap + residue not selected → flash "denied".
 *  - ArrowLeft / ArrowRight  → move the keyboard focus ring along the chain.
 *  - Enter / Space on focused residue  → toggle.
 *  - "Center on selection" button  → animates camera to selected residues.
 *
 * Accessibility
 * -------------
 * Mol*'s canvas is inherently not keyboard accessible (it is a WebGL
 * surface), so we attach a parallel focus ring that lives on an off-screen
 * button + visible badge showing the currently focused residue. The badge
 * doubles as a screen-reader live region.
 */

// Mol* must only render on the client.
const MolstarViewer = dynamic(
  () =>
    import("@/components/viewer/MolstarViewer").then((m) => ({
      default: m.MolstarViewer,
    })),
  { ssr: false, loading: () => <ViewerSkeleton /> },
);

export interface HotspotPicker3DProps {
  /** Raw PDB or mmCIF text for the target structure. */
  pdbText: string;
  /** Explicit structure format. Auto-detected from the text when omitted. */
  structureFormat?: StructureFormat;
  /** Target chain ID: hotspots only toggle on this chain. */
  chainId: string;
  /** Every polymer chain in this target structure. All are rendered as target. */
  targetChainIds?: string[];
  /** Controlled selection Set (author-seq IDs). */
  selected: Set<number>;
  /** Emits a single residue to toggle: parent owns the set. */
  onToggle: (resi: number) => void;
  /** True when the parent has hit the hotspot cap. */
  atCap: boolean;
  /** Ordered residue IDs for keyboard navigation. */
  residues: readonly number[];
  /** Optional. e.g. "membrane": reserved for future palette tweaks. */
  targetClass?: string;
  /** Optional className on the wrapper. */
  className?: string;
}

const NO_BINDER_CHAINS: string[] = [];

export function HotspotPicker3D({
  pdbText,
  structureFormat,
  chainId,
  targetChainIds,
  selected,
  onToggle,
  atCap,
  residues,
  targetClass: _targetClass,
  className,
}: HotspotPicker3DProps) {
  const [structureUrl, setStructureUrl] = useState<string | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [focused, setFocused] = useState<number | null>(null);
  const [denied, setDenied] = useState(false);
  const [denialMessage, setDenialMessage] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [centering, setCentering] = useState(false);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const denialTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const centerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resolvedFormat: StructureFormat =
    structureFormat ?? (looksLikeCif(pdbText) ? "cif" : "pdb");

  // Turn the PDB text into an object URL for Mol* to fetch. We rebuild this
  // whenever the text changes (re-uploads, preset swaps) and revoke the
  // previous one to prevent a leak.
  useEffect(() => {
    if (!pdbText) {
      setStructureUrl(null);
      return;
    }
    const blob = new Blob([pdbText], {
      type: resolvedFormat === "cif" ? "chemical/x-cif" : "chemical/x-pdb",
    });
    const url = URL.createObjectURL(blob);
    setStructureUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pdbText, resolvedFormat]);

  const highlights: DesignHighlight[] = useMemo(
    () => buildHotspotHighlights(selected, chainId),
    [selected, chainId],
  );
  const resolvedTargetChainIds = useMemo(
    () => Array.from(new Set([...(targetChainIds ?? []), chainId])),
    [chainId, targetChainIds],
  );
  const residueSet = useMemo(() => new Set(residues), [residues]);

  const flashDenied = useCallback((message: string) => {
    setDenied(true);
    setDenialMessage(message);
    if (denialTimer.current) clearTimeout(denialTimer.current);
    denialTimer.current = setTimeout(() => {
      setDenied(false);
      setDenialMessage(null);
    }, 1600);
  }, []);

  useEffect(() => {
    return () => {
      if (denialTimer.current) clearTimeout(denialTimer.current);
      if (centerTimer.current) clearTimeout(centerTimer.current);
    };
  }, []);

  const attemptToggle = useCallback(
    (resi: number) => {
      // Reuse the same clamp logic as the lib helpers so UX matches 2D view.
      const { denied: willDeny } = clampSelectionToggle(
        selected,
        resi,
        atCap && !selected.has(resi) ? selected.size : Infinity,
      );
      if (willDeny) {
        flashDenied("20 hotspot limit reached");
        return;
      }
      onToggle(resi);
    },
    [atCap, flashDenied, onToggle, selected],
  );

  const onResidueClick = useCallback(
    (id: { chain: string; resi: number }) => {
      if (id.chain !== chainId) return; // only the target chain is toggleable
      if (!residueSet.has(id.resi)) return;
      setFocused(id.resi);
      attemptToggle(id.resi);
    },
    [attemptToggle, chainId, residueSet],
  );

  const onResidueHover = useCallback(
    (id: { chain: string; resi: number } | null) => {
      if (!id || id.chain !== chainId) {
        setHovered(null);
        return;
      }
      setHovered(id.resi);
    },
    [chainId],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const next = nextFocusResidue(residues as number[], focused, e.key);
        if (next != null) setFocused(next);
      } else if ((e.key === "Enter" || e.key === " ") && focused != null) {
        e.preventDefault();
        attemptToggle(focused);
      }
    },
    [attemptToggle, focused, residues],
  );

  const onCenter = useCallback(() => {
    if (selected.size === 0) return;
    if (centerTimer.current) clearTimeout(centerTimer.current);
    setCentering(true);
    setAnnouncement(
      `Centering camera on ${selected.size} selected hotspot${selected.size === 1 ? "" : "s"}`,
    );
    setFocusRequest((value) => value + 1);
    centerTimer.current = setTimeout(() => {
      setCentering(false);
      setAnnouncement(
        `Camera centered on ${selected.size} selected hotspot${selected.size === 1 ? "" : "s"}`,
      );
    }, 500);
  }, [selected.size]);

  const status = useMemo(() => {
    if (selected.size === 0) return "No hotspots selected";
    return `${selected.size} hotspot${selected.size === 1 ? "" : "s"} selected`;
  }, [selected.size]);

  return (
    <div
      className={cn(
        "flex flex-col gap-3",
        denied && "hotspot-picker-3d-denied",
        className,
      )}
      onKeyDown={onKeyDown}
      role="application"
      aria-label={`3D hotspot picker for chain ${chainId}`}
      tabIndex={0}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-paper">
            <Info className="h-3 w-3" aria-hidden />
          </span>
          <div>
            <p className="font-sans text-[13px] text-ink">
              Click a residue on chain {chainId} to toggle a hotspot.
            </p>
            <p className="mt-0.5 font-sans text-[11px] text-graphite-soft">
              Every visible chain is part of the target; only chain {chainId} is
              editable.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onCenter}
          disabled={selected.size === 0 || centering}
          aria-label="Center camera on selected hotspots"
          className={cn(
            "inline-flex h-9 items-center gap-2 rounded-full border px-3.5 font-mono text-[11px] transition-all",
            "border-lattice-strong bg-paper text-ink hover:border-ink",
            "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-lattice-strong",
          )}
        >
          {centering ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
          ) : (
            <Focus className="w-3.5 h-3.5" aria-hidden />
          )}
          {centering ? "Centering…" : "Center selected"}
        </button>
      </div>

      <div
        className={cn(
          "relative rounded-lg border border-lattice bg-paper overflow-hidden",
          "h-[390px] sm:h-[460px] xl:h-[500px] transition-all duration-200",
          denied && "ring-2 ring-crane-red",
        )}
      >
        {structureUrl ? (
          <MolstarViewer
            structureUrl={structureUrl}
            format={resolvedFormat}
            targetChainIds={resolvedTargetChainIds}
            binderChainIds={NO_BINDER_CHAINS}
            highlights={highlights}
            focusHighlightsRequest={focusRequest}
            onResidueClick={onResidueClick}
            onResidueHover={onResidueHover}
            ariaLabel={`3D structure viewer for chain ${chainId}`}
          />
        ) : (
          <ViewerSkeleton />
        )}

        {denialMessage && (
          <div
            role="status"
            aria-live="assertive"
            className="absolute top-3 left-1/2 -translate-x-1/2 rounded-full bg-crane-red px-4 py-1.5 font-sans text-[12px] text-paper shadow-lg"
          >
            {denialMessage}
          </div>
        )}

        {(hovered != null || focused != null) && (
          <div
            aria-hidden
            className="pointer-events-none absolute bottom-3 left-3 rounded-full bg-paper/95 px-3 py-1 font-mono text-[11px] text-ink shadow-sm"
          >
            {hovered != null ? `Hover: ${chainId}:${hovered}` : null}
            {hovered == null && focused != null
              ? `Focus: ${chainId}:${focused}`
              : null}
          </div>
        )}
      </div>

      <div className="flex min-h-7 items-center justify-between gap-3 px-1 font-sans text-[11px] text-graphite-soft">
        <span id="hotspot-picker-3d-announcer" aria-live="polite" role="status">
          {announcement ?? status}
        </span>
        {focused != null && (
          <span className="font-mono text-[11px] text-graphite">
            Keyboard focus: {chainId}:{focused}
          </span>
        )}
      </div>
    </div>
  );
}

function ViewerSkeleton() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full w-full items-center justify-center font-sans text-[13px] text-graphite-soft"
    >
      Preparing 3D viewer…
    </div>
  );
}
