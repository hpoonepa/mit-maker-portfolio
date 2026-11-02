"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";
import type { CameraState, ViewerProps } from "./types";

/**
 * Compare-mode layout that renders 2-4 Mol* viewers with a shared camera.
 *
 * A single "leader" viewer emits camera changes which the siblings mirror.
 * Whichever viewer the user clicks becomes the leader: mirrored back at
 * the others without firing a feedback loop because siblings receive the
 * camera via `syncedCamera` (declarative) rather than re-emitting.
 */

const MolstarViewer = dynamic<ViewerProps>(
  () => import("./MolstarViewer").then((m) => m.MolstarViewer),
  {
    ssr: false,
    loading: () => (
      <div
        role="status"
        aria-live="polite"
        className="flex h-full min-h-[360px] items-center justify-center rounded-lg border border-lattice bg-paper-fold/40 font-sans text-[12px] text-graphite-soft"
      >
        Loading viewer…
      </div>
    ),
  }
);

export interface SideBySideDesign {
  id: string;
  label: string;
  /** Seed number or similar identifier shown in the corner. */
  sublabel?: string;
  structureUrl: string;
  targetChainIds?: string[];
  binderChainIds?: string[];
  highlights?: ViewerProps["highlights"];
}

export interface SideBySideProps {
  designs: SideBySideDesign[];
  /** Optional CSS class on the grid wrapper. */
  className?: string;
}

export function SideBySide({ designs, className }: SideBySideProps) {
  const [camera, setCamera] = useState<CameraState | null>(null);
  const [leaderId, setLeaderId] = useState<string | null>(
    designs[0]?.id ?? null
  );

  const onCameraChange = useCallback(
    (id: string, next: CameraState) => {
      if (leaderId !== id) return;
      setCamera(next);
    },
    [leaderId]
  );

  if (designs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-lattice-strong bg-paper-fold/30 p-10 text-center font-sans text-[14px] text-graphite">
        Select up to four designs to compare.
      </div>
    );
  }

  // 2 designs: side by side. 3-4 designs: 2x2 grid.
  const gridCols =
    designs.length <= 2 ? "grid-cols-1 md:grid-cols-2" : "grid-cols-2";

  return (
    <div
      className={
        (className ? className + " " : "") +
        `grid gap-4 ${gridCols}`
      }
      role="region"
      aria-label="Compare designs"
    >
      {designs.slice(0, 4).map((d) => {
        const isLeader = d.id === leaderId;
        return (
          <div
            key={d.id}
            className="relative h-[420px] rounded-lg border border-lattice overflow-hidden"
            onMouseDown={() => setLeaderId(d.id)}
            onFocus={() => setLeaderId(d.id)}
          >
            <div className="absolute top-3 left-3 z-10 rounded-lg bg-paper/90 px-2.5 py-1 font-sans text-[12px] text-ink">
              {d.label}
              {d.sublabel && (
                <span className="ml-2 text-graphite-soft">{d.sublabel}</span>
              )}
              {isLeader && (
                <span className="ml-2 inline-flex items-center gap-1 text-crane">
                  <span className="h-1.5 w-1.5 rounded-full bg-crane" />
                  leader
                </span>
              )}
            </div>
            <MolstarViewer
              structureUrl={d.structureUrl}
              targetChainIds={d.targetChainIds}
              binderChainIds={d.binderChainIds}
              highlights={d.highlights}
              syncedCamera={isLeader ? null : camera}
              onCameraChange={(c) => onCameraChange(d.id, c)}
              ariaLabel={`Design ${d.label}`}
            />
          </div>
        );
      })}
    </div>
  );
}

export default SideBySide;
