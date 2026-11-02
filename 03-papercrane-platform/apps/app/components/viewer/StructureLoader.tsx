"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, AlertTriangle, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { PdbInput } from "./PdbInput";
import { headFetchPdb, PdbFetchError, type PdbFormat } from "@/lib/pdb/fetch";
import {
  sourceFromFile,
  sourceFromPdbId,
  type CifSource,
} from "@/lib/pdb/cif-loader";
import type { ViewerProps } from "./types";

/**
 * Mol* is ~2 MB gzipped and pulls browser globals at module scope. We
 * dynamic-import the viewer with `ssr: false` so it never executes on the
 * server, and so the bundle only ships once the user actually opens a page
 * that loads a structure.
 */
const MolstarViewer = dynamic(
  () => import("./MolstarViewer").then((m) => m.MolstarViewer),
  {
    ssr: false,
    loading: () => (
      <div
        className="flex h-full w-full items-center justify-center bg-graphite-50 text-sm text-graphite-500"
        data-testid="molstar-bundle-loading"
      >
        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
        Initialising viewer…
      </div>
    ),
  },
);

type LoadStatus = "idle" | "validating" | "ready" | "error";

export interface StructureLoaderProps {
  /** Optional PDB ID to load on mount (e.g. from a URL slug). */
  initialPdbId?: string;
  /** Allow drag/drop uploads of local .pdb / .cif files. */
  enableUpload?: boolean;
  /** Forwarded to the underlying viewer for hotspot integration. */
  onResidueClick?: ViewerProps["onResidueClick"];
  onResidueHover?: ViewerProps["onResidueHover"];
  onStructureLoad?: ViewerProps["onStructureLoad"];
  /** Hotspot pins to render on the structure. */
  highlights?: ViewerProps["highlights"];
  /** Override default chain assignment (target = "A"). */
  targetChainIds?: ViewerProps["targetChainIds"];
  binderChainIds?: ViewerProps["binderChainIds"];
  className?: string;
}

/**
 * Drives the Mol* viewer from a user-supplied PDB ID or local file.
 *
 * Responsibilities:
 *   - Validate the PDB ID shape, then HEAD the RCSB CDN to surface 404s
 *     before mounting the viewer.
 *   - Show a friendly loading spinner with the resolved label.
 *   - Show a clear error card with a "Try a different PDB ID" CTA.
 *   - Pass `onResidueClick` straight through so the existing
 *     `HotspotPicker3D` keeps working unchanged.
 */
/** sessionStorage key for memoised PDB-ID fetch results. */
const PDB_CACHE_PREFIX = "pc:pdb:";
/** Minimum hold time for the loading skeleton to avoid spinner flash. */
const MIN_LOADING_MS = 200;

interface CachedResolution {
  format: PdbFormat;
  ts: number;
}

function readPdbCache(id: string): CachedResolution | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(
      PDB_CACHE_PREFIX + id.trim().toUpperCase(),
    );
    if (!raw) return null;
    const parsed = JSON.parse(raw) as
      | CachedResolution
      | { format?: unknown; ts?: unknown };
    if (
      parsed.format !== "cif" &&
      parsed.format !== "pdb" &&
      parsed.format !== "mmcif"
    ) {
      return null;
    }
    if (typeof parsed.ts !== "number") return null;
    // Stale after 30 minutes.
    if (Date.now() - parsed.ts > 30 * 60 * 1000) return null;
    return {
      format: parsed.format === "mmcif" ? "cif" : parsed.format,
      ts: parsed.ts,
    };
  } catch {
    return null;
  }
}

function writePdbCache(id: string, format: PdbFormat): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      PDB_CACHE_PREFIX + id.trim().toUpperCase(),
      JSON.stringify({ format, ts: Date.now() } satisfies CachedResolution),
    );
  } catch {
    /* private mode / quota: non-fatal */
  }
}

function clearPdbCache(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(
      PDB_CACHE_PREFIX + id.trim().toUpperCase(),
    );
  } catch {
    /* non-fatal */
  }
}

export function StructureLoader({
  initialPdbId,
  enableUpload = true,
  onResidueClick,
  onResidueHover,
  onStructureLoad,
  highlights,
  targetChainIds,
  binderChainIds,
  className,
}: StructureLoaderProps) {
  const [status, setStatus] = useState<LoadStatus>("idle");
  const [source, setSource] = useState<CifSource | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<
    "not-found" | "network" | "blocked" | "offline" | "unknown"
  >("unknown");
  const [lastTriedId, setLastTriedId] = useState<string | null>(null);
  /** Bumped on retry to force a fresh fetch even when the URL is unchanged. */
  const [retryNonce, setRetryNonce] = useState(0);

  // Track the active source so we can revoke blob URLs on replacement.
  const sourceRef = useRef<CifSource | null>(null);
  useEffect(() => {
    sourceRef.current = source;
  }, [source]);
  useEffect(() => () => sourceRef.current?.release(), []);

  const swapSource = useCallback((next: CifSource | null) => {
    sourceRef.current?.release();
    sourceRef.current = next;
    setSource(next);
  }, []);

  const loadPdbId = useCallback(
    async (id: string, opts?: { bypassCache?: boolean }) => {
      setStatus("validating");
      setErrorMsg(null);
      setLastTriedId(id);
      const startedAt = Date.now();

      // Fast path: use the cached `cif`/`pdb` choice from a previous probe so
      // we skip the HEAD round-trip entirely.
      if (!opts?.bypassCache) {
        const cached = readPdbCache(id);
        if (cached) {
          const next = sourceFromPdbId(id, cached.format);
          swapSource(next);
          setStatus("ready");
          return;
        }
      }

      const ctrl = new AbortController();
      try {
        // Probe RCSB: `auto` tries `.cif` first, falls back to `.pdb`,
        // and retries 5xx with backoff. We use the resolved format the
        // probe returns so the viewer stays in sync.
        const resolved = await headFetchPdb(id, "auto", ctrl.signal);
        writePdbCache(id, resolved.format);
        const next = sourceFromPdbId(id, resolved.format);
        // Hold the loading state for at least MIN_LOADING_MS so the
        // skeleton doesn't flash when the network is fast.
        const elapsed = Date.now() - startedAt;
        if (elapsed < MIN_LOADING_MS) {
          await new Promise((r) => setTimeout(r, MIN_LOADING_MS - elapsed));
        }
        swapSource(next);
        setStatus("ready");
      } catch (err) {
        const raw =
          err instanceof PdbFetchError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load structure.";
        // Classify so the UI can render the right copy + icon.
        const status404 =
          err instanceof PdbFetchError &&
          (err as unknown as { status?: number }).status === 404;
        if (status404 || /\b404\b|not found/i.test(raw)) {
          setErrorKind("not-found");
          setErrorMsg(`PDB ID "${id}" not found in RCSB.`);
        } else if (
          typeof navigator !== "undefined" &&
          navigator.onLine === false
        ) {
          setErrorKind("offline");
          setErrorMsg("You're offline: reconnect and try again.");
        } else if (/csp|content security|blocked/i.test(raw)) {
          setErrorKind("blocked");
          setErrorMsg("Blocked by browser security policy.");
        } else if (/failed to fetch|networkerror|cors/i.test(raw)) {
          setErrorKind("network");
          setErrorMsg("Network error: RCSB couldn't be reached.");
        } else {
          setErrorKind("unknown");
          setErrorMsg(raw);
        }
        setStatus("error");
      }
    },
    [swapSource],
  );

  const loadFile = useCallback(
    (file: File) => {
      try {
        const next = sourceFromFile(file);
        setLastTriedId(null);
        setErrorMsg(null);
        swapSource(next);
        setStatus("ready");
      } catch (err) {
        setErrorMsg(
          err instanceof Error ? err.message : "Could not read uploaded file.",
        );
        setStatus("error");
      }
    },
    [swapSource],
  );

  const reset = useCallback(() => {
    swapSource(null);
    setErrorMsg(null);
    setErrorKind("unknown");
    setStatus("idle");
  }, [swapSource]);

  /** Re-execute the previous fetch: clears cache so we always hit RCSB. */
  const retryLastLoad = useCallback(() => {
    if (!lastTriedId) return;
    clearPdbCache(lastTriedId);
    setRetryNonce((n) => n + 1);
    void loadPdbId(lastTriedId, { bypassCache: true });
  }, [lastTriedId, loadPdbId]);

  // Boot with an initial PDB ID if one was provided (e.g. /target/6X1A).
  useEffect(() => {
    if (!initialPdbId) return;
    void loadPdbId(initialPdbId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPdbId]);

  return (
    <div
      className={cn("flex h-full w-full flex-col gap-3", className)}
      data-testid="structure-loader"
      data-status={status}
    >
      <PdbInput
        onPdbId={loadPdbId}
        onFile={enableUpload ? loadFile : undefined}
        currentLabel={source?.label}
        loading={status === "validating"}
      />

      <div className="relative flex-1 min-h-[420px] overflow-hidden rounded-lg border border-graphite-200 bg-graphite-50">
        {status === "idle" && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 p-8 text-center text-graphite-500">
            <span className="text-sm font-medium text-graphite-700">
              Pick a target or paste a PDB ID
            </span>
            <span className="text-xs">
              Try{" "}
              <button
                type="button"
                onClick={() => void loadPdbId("6X1A")}
                className="font-mono text-crane-600 underline-offset-2 hover:underline"
              >
                6X1A
              </button>{" "}
              to see a sample structure
              {enableUpload ? ", or drop a .pdb / .cif file above" : ""}.
            </span>
          </div>
        )}

        {status === "validating" && (
          <div
            role="status"
            aria-live="polite"
            className="flex h-full w-full flex-col items-center justify-center gap-3 p-8 text-center"
            data-testid="structure-loader-validating"
          >
            <div
              aria-hidden="true"
              className="h-7 w-7 animate-spin rounded-full border-2 border-lattice-strong border-t-crane motion-reduce:animate-none"
            />
            <span className="text-sm font-medium text-graphite-700">
              Folding {lastTriedId ?? "structure"}…
            </span>
            <span className="text-xs text-graphite-500">
              Fetching from RCSB
            </span>
          </div>
        )}

        {status === "error" && (
          <div
            role="alert"
            className="flex h-full w-full flex-col items-center justify-center gap-3 p-8 text-center"
            data-testid="structure-loader-error"
            data-error-kind={errorKind}
          >
            <AlertTriangle
              className="h-8 w-8 text-red-500"
              aria-hidden="true"
            />
            <div>
              <div className="text-sm font-semibold text-graphite-900">
                {errorKind === "not-found"
                  ? "PDB ID not found"
                  : errorKind === "offline"
                    ? "You're offline"
                    : errorKind === "blocked"
                      ? "Blocked by browser policy"
                      : "Couldn't load "}
                {errorKind === "unknown" || errorKind === "network" ? (
                  lastTriedId ? (
                    <span className="font-mono">{lastTriedId}</span>
                  ) : (
                    "structure"
                  )
                ) : null}
              </div>
              <div className="mt-1 text-xs text-graphite-600">{errorMsg}</div>
            </div>
            <div className="flex items-center gap-2">
              {lastTriedId && errorKind !== "not-found" && (
                <button
                  type="button"
                  onClick={retryLastLoad}
                  data-testid="structure-loader-retry"
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs",
                    "border-crane-500 bg-crane-500 text-white hover:border-crane-600 hover:bg-crane-600",
                  )}
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  Retry
                </button>
              )}
              <button
                type="button"
                onClick={reset}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs",
                  "border-graphite-200 text-graphite-700 hover:border-crane-500 hover:text-crane-600",
                )}
              >
                Try a different PDB ID
              </button>
            </div>
          </div>
        )}

        {status === "ready" && source && (
          <MolstarViewer
            // Append a cache-busting hash on retry so the memoised viewer
            // detects a URL change and runs the load effect again. The
            // RCSB CDN ignores the hash so we don't waste bandwidth.
            structureUrl={
              retryNonce > 0 ? `${source.url}#r=${retryNonce}` : source.url
            }
            format={source.format}
            highlights={highlights}
            targetChainIds={targetChainIds}
            binderChainIds={binderChainIds}
            onResidueClick={onResidueClick}
            onResidueHover={onResidueHover}
            onStructureLoad={onStructureLoad}
            ariaLabel={`Mol* viewer: ${source.label}`}
            className="absolute inset-0"
          />
        )}
      </div>
    </div>
  );
}

export default StructureLoader;
