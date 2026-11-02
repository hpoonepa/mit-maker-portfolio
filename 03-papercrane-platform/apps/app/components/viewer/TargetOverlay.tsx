"use client";

import dynamic from "next/dynamic";
import type { DesignHighlight, ViewerProps } from "./types";

/**
 * Target + binder overlay: a thin wrapper around MolstarViewer that
 * enforces the Paper Crane convention for which chains are target vs
 * binder, and exposes `hotspots` as the explicit API for the highlights.
 *
 * Dashboards show a hero instance of this on each design card: it is NOT
 * the compare mode view (that's SideBySide).
 */

const MolstarViewer = dynamic<ViewerProps>(
  () => import("./MolstarViewer").then((m) => m.MolstarViewer),
  {
    ssr: false,
    loading: () => (
      <div
        role="status"
        aria-live="polite"
        className="flex h-full min-h-[420px] items-center justify-center rounded-lg border border-lattice bg-paper-fold/40 font-sans text-[12px] text-graphite-soft"
      >
        Loading viewer…
      </div>
    ),
  }
);

export interface TargetOverlayProps {
  structureUrl: string;
  /** Chains considered "target". Defaults to ["A"]. */
  targetChainIds?: string[];
  /** Chains considered "binder". Defaults to ["B"]. */
  binderChainIds?: string[];
  /** Interface hotspots shown as yellow spheres on the target. */
  hotspots?: DesignHighlight[];
  /** Auto-rotate on mount. Respects prefers-reduced-motion. */
  autoRotate?: boolean;
  /** Optional wrapper className. */
  className?: string;
  /** Screen-reader label. */
  ariaLabel?: string;
}

export function TargetOverlay({
  structureUrl,
  targetChainIds = ["A"],
  binderChainIds = ["B"],
  hotspots,
  autoRotate = true,
  className,
  ariaLabel,
}: TargetOverlayProps) {
  return (
    <MolstarViewer
      structureUrl={structureUrl}
      targetChainIds={targetChainIds}
      binderChainIds={binderChainIds}
      highlights={hotspots}
      autoRotate={autoRotate}
      className={className}
      ariaLabel={ariaLabel ?? "Target and binder complex"}
    />
  );
}

export default TargetOverlay;
