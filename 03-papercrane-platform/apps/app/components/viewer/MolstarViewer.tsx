"use client";

import { memo, useCallback, useRef, useState } from "react";
import {
  AlertTriangle,
  Camera,
  Layers,
  Loader2,
  Pause,
  Play,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMolstar } from "./useMolstar";
import type {
  DesignHighlight,
  RepresentationStyle,
  ViewerProps,
} from "./types";
import styles from "./MolstarViewer.module.css";
import { chainColor, cssColor, HOTSPOT_COLOR } from "./palette";

const REPRESENTATIONS: RepresentationStyle[] = [
  "cartoon",
  "atoms",
  "surface",
  "ribbon",
];

/**
 * Interactive Mol* viewer. Client-only.
 *
 * IMPORTANT: import this component via `next/dynamic({ ssr: false })`: Mol*
 * pulls in browser APIs at module scope and will crash in a Node render.
 *
 * The component is wrapped in `React.memo` with a custom comparator so that
 * highlight-only changes (e.g. clicking a residue in the hotspot picker) do
 * not retrigger the heavy structure download. Only changes to
 * `structureUrl` / `format` cause a reload; chain colours and highlights are
 * diffed inside the hook.
 */
function MolstarViewerImpl(props: ViewerProps) {
  const {
    structureUrl,
    format,
    targetChainIds,
    binderChainIds,
    highlights,
    focusHighlightsRequest,
    autoRotate: initialAutoRotate = false,
    onCameraChange,
    syncedCamera,
    onResidueClick,
    onResidueHover,
    onStructureLoad,
    className,
    ariaLabel = "Protein structure viewer",
  } = props;

  const hostRef = useRef<HTMLDivElement | null>(null);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const [representation, setRepresentation] = useState<
    RepresentationStyle | undefined
  >(props.representation);
  const [autoRotate, setAutoRotate] = useState<boolean>(initialAutoRotate);

  const attachHost = useCallback((node: HTMLDivElement | null) => {
    hostRef.current = node;
    setHost(node);
  }, []);

  const {
    status,
    structureSummary,
    activeRepresentation,
    error,
    structureLoading,
    retryStructure,
    resetCamera,
    takeScreenshot,
    reducedMotion,
  } = useMolstar({
    container: host,
    structureUrl,
    format,
    targetChainIds,
    binderChainIds,
    highlights,
    focusHighlightsRequest,
    representation,
    autoRotate,
    onCameraChange,
    syncedCamera,
    onResidueClick,
    onResidueHover,
    onStructureLoad,
  });

  const onScreenshot = useCallback(async () => {
    const uri = await takeScreenshot();
    if (!uri) return;
    const a = document.createElement("a");
    a.href = uri;
    a.download = "papercrane-design.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }, [takeScreenshot]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "r" || e.key === "R") {
        resetCamera();
      } else if (e.key === " ") {
        e.preventDefault();
        setAutoRotate((v) => !v);
      } else if (e.key === "c" || e.key === "C") {
        setRepresentation(
          REPRESENTATIONS[
            (REPRESENTATIONS.indexOf(activeRepresentation) + 1) %
              REPRESENTATIONS.length
          ],
        );
      }
    },
    [resetCamera, activeRepresentation],
  );

  // Distinguish "no WebGL" from "load failed" so users get a clearer hint.
  const isWebGLError = !!error && /WebGL|3D|chrome|firefox/i.test(error);

  return (
    <div
      className={cn(styles.wrapper, className)}
      role="group"
      aria-label={ariaLabel}
      tabIndex={0}
      onKeyDown={onKeyDown}
      data-testid="e2e-molstar-viewer"
      data-molstar-status={status}
      data-molstar-structure-loading={structureLoading || undefined}
    >
      <div ref={attachHost} className={styles.canvas} aria-hidden="true" />

      {(status === "idle" || status === "loading" || structureLoading) && (
        <div
          className={styles.skeleton}
          role="status"
          aria-live="polite"
          data-testid="molstar-init-loading"
        >
          <Loader2
            className="mr-2 inline h-3.5 w-3.5 animate-spin align-[-2px]"
            aria-hidden="true"
          />
          {status === "ready"
            ? "Loading structure…"
            : "Initializing 3D viewer…"}
        </div>
      )}

      {status === "error" && error && (
        <div className={styles.error} role="alert" data-testid="molstar-error">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          <span className={styles.errorLabel}>
            {isWebGLError ? "3D Not Supported" : "Viewer Error"}
          </span>
          <span>{error}</span>
          {!isWebGLError && (
            <button
              type="button"
              onClick={retryStructure}
              className="mt-2 inline-flex items-center gap-2 rounded-full border border-crane-deep bg-paper px-3.5 py-1.5 font-sans text-[12px] text-crane-deep transition-colors hover:bg-crane-glow"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry structure
            </button>
          )}
        </div>
      )}

      {status === "ready" && !structureLoading && (
        <div className={styles.overlay} aria-hidden="false">
          <div className={styles.legend}>
            {structureSummary?.chains.map((chain, i) => (
              <span
                key={chain.chainId}
                className={styles.swatch}
                style={{
                  color: cssColor(
                    chainColor(
                      i,
                      chain.chainId,
                      targetChainIds ?? [],
                      binderChainIds ?? [],
                    ),
                  ),
                }}
              >
                {binderChainIds?.includes(chain.chainId)
                  ? "Binder"
                  : targetChainIds?.includes(chain.chainId)
                    ? "Target"
                    : "Chain"}{" "}
                {chain.chainId}
              </span>
            ))}
            {highlights && highlights.length > 0 && (
              <span
                className={styles.swatch}
                style={{ color: cssColor(HOTSPOT_COLOR) }}
              >
                Hotspots
              </span>
            )}
          </div>

          <div className={styles.bottomBar}>
            {structureSummary && structureSummary.backboneBreaks > 0 && (
              <p className={styles.structureNotice} role="status">
                <strong>
                  {structureSummary.backboneBreaks} backbone{" "}
                  {structureSummary.backboneBreaks === 1 ? "break" : "breaks"}{" "}
                  in the saved coordinates.
                </strong>{" "}
                Dashed links in ribbon views mark these gaps.
              </p>
            )}
            <div
              className={styles.controls}
              role="toolbar"
              aria-label="Viewer controls"
            >
              <span className={styles.representationLabel}>
                {activeRepresentation}
              </span>
              <button
                type="button"
                className={styles.control}
                onClick={() => setAutoRotate((v) => !v)}
                aria-label={autoRotate ? "Pause rotation" : "Play rotation"}
                aria-pressed={autoRotate}
                data-active={autoRotate || undefined}
                disabled={reducedMotion}
                title={
                  reducedMotion
                    ? "Disabled: reduced motion preference"
                    : autoRotate
                      ? "Pause rotation (Space)"
                      : "Play rotation (Space)"
                }
              >
                {autoRotate ? (
                  <Pause className="w-3.5 h-3.5" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
              </button>

              <button
                type="button"
                className={styles.control}
                onClick={() =>
                  setRepresentation(
                    REPRESENTATIONS[
                      (REPRESENTATIONS.indexOf(activeRepresentation) + 1) %
                        REPRESENTATIONS.length
                    ],
                  )
                }
                aria-label={`Switch representation (current: ${activeRepresentation})`}
                title="Cycle representation (C)"
              >
                <Layers className="w-3.5 h-3.5" />
              </button>

              <button
                type="button"
                className={styles.control}
                onClick={resetCamera}
                aria-label="Reset camera"
                title="Reset camera (R)"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>

              <button
                type="button"
                className={styles.control}
                onClick={onScreenshot}
                aria-label="Download screenshot"
                title="Download screenshot"
              >
                <Camera className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Cheap deep-equal for highlight arrays. We compare by chain+resi rather than
 * object identity because callers (HotspotPicker) build a fresh array on
 * every render.
 */
function highlightsEqual(
  a?: DesignHighlight[],
  b?: DesignHighlight[],
): boolean {
  if (a === b) return true;
  if (!a || !b) return a === b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const x = a[i];
    const y = b[i];
    if (!x || !y) return false;
    if (x.chainId !== y.chainId || x.resi !== y.resi || x.style !== y.style)
      return false;
  }
  return true;
}

function arrayEqual(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b) return a === b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Custom comparator: a viewer reload is expensive, so we explicitly opt out
 * of re-rendering when only callbacks change (callbacks are read via refs in
 * `useMolstar`). Highlights / chain assignments are compared structurally.
 */
function arePropsEqual(a: ViewerProps, b: ViewerProps): boolean {
  return (
    a.structureUrl === b.structureUrl &&
    a.format === b.format &&
    a.representation === b.representation &&
    a.autoRotate === b.autoRotate &&
    a.focusHighlightsRequest === b.focusHighlightsRequest &&
    a.ariaLabel === b.ariaLabel &&
    a.className === b.className &&
    a.syncedCamera === b.syncedCamera &&
    arrayEqual(a.targetChainIds, b.targetChainIds) &&
    arrayEqual(a.binderChainIds, b.binderChainIds) &&
    highlightsEqual(a.highlights, b.highlights)
  );
}

export const MolstarViewer = memo(MolstarViewerImpl, arePropsEqual);
MolstarViewer.displayName = "MolstarViewer";

export default MolstarViewer;
