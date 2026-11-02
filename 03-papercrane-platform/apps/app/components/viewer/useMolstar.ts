"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Model } from "molstar/lib/mol-model/structure";
import {
  summarizeModel,
  defaultRepresentation,
  type StructureSummary,
} from "./structureSummary";
import { VIEWER_BACKGROUND, HOTSPOT_COLOR, chainColor } from "./palette";
import type {
  CameraState,
  DesignHighlight,
  RepresentationStyle,
  StructureFormat,
  ViewerProps,
} from "./types";

/**
 * React hook that owns the lifecycle of a Mol* plugin instance.
 *
 * Mol* ~4.8.0 API notes:
 *   - `createPluginUI` lives at `molstar/lib/mol-plugin-ui/index` and mounts
 *     the React-based plugin into a container. We use `renderReact18` as
 *     the render callback so it plays nice with our React 18 tree.
 *   - `plugin.builders.structure.*` are the high-level helpers we use to
 *     load and color structures without dropping into state-tree land.
 *   - `plugin.canvas3d` exposes camera + animation subscriptions.
 *
 * The entire Mol* import chain is dynamic so the ~2 MB gzipped bundle only
 * loads when the hook first runs. Next.js dynamic import of the consumer
 * handles the route-level split; the dynamic import inside the hook keeps
 * it out of anything that accidentally pulls the types.
 */

/** Status of the underlying plugin. */
type Status = "idle" | "loading" | "ready" | "error";

/**
 * Quick WebGL probe: Mol* requires WebGL2 (preferred) or WebGL1. We surface
 * a friendly "your browser doesn't support 3D" message instead of letting
 * Mol*'s opaque internal failure bubble up.
 */
function detectWebGLSupport(): { ok: boolean; reason?: string } {
  if (typeof window === "undefined") {
    return { ok: false, reason: "Server-side render" };
  }
  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl");
    if (!gl) {
      return {
        ok: false,
        reason: "Your browser doesn't support 3D: try Chrome or Firefox.",
      };
    }
    return { ok: true };
  } catch {
    return {
      ok: false,
      reason: "Your browser doesn't support 3D: try Chrome or Firefox.",
    };
  }
}

interface Options extends Pick<
  ViewerProps,
  | "structureUrl"
  | "format"
  | "targetChainIds"
  | "binderChainIds"
  | "highlights"
  | "focusHighlightsRequest"
  | "representation"
  | "autoRotate"
  | "onCameraChange"
  | "syncedCamera"
  | "onResidueClick"
  | "onResidueHover"
  | "onStructureLoad"
> {
  /** DOM node the plugin should mount into. */
  container: HTMLDivElement | null;
}

interface Controls {
  status: Status;
  structureSummary: StructureSummary | null;
  activeRepresentation: RepresentationStyle;
  error: string | null;
  /** True while Mol* is downloading/parsing the current structure. */
  structureLoading: boolean;
  /** Retry the current URL after a download/parse failure. */
  retryStructure: () => void;
  /** Reset the camera to fit the loaded structure. */
  resetCamera: () => void;
  /** Swap the polymer representation. */
  setRepresentation: (style: RepresentationStyle) => void;
  /** Toggle the rotation animation (respecting prefers-reduced-motion). */
  setAutoRotate: (on: boolean) => void;
  /** Produce a PNG data URL of the current canvas. */
  takeScreenshot: () => Promise<string | null>;
  /** Current camera: exposed so SideBySide can mirror it. */
  camera: CameraState | null;
  /** True when the OS reports `prefers-reduced-motion: reduce`. */
  reducedMotion: boolean;
}

const NO_CHAINS: string[] = [];
const NO_HIGHLIGHTS: DesignHighlight[] = [];

function inferFormat(url: string, explicit?: StructureFormat): StructureFormat {
  if (explicit) return explicit;
  const lower = url.toLowerCase().split("?")[0] ?? "";
  if (lower.endsWith(".pdb") || lower.endsWith(".pdb.gz")) return "pdb";
  return "cif";
}

/**
 * Fetch structure text before creating Molstar state. Molstar's download
 * builder reverts failed HTTP transforms and then reports the misleading
 * "Invalid data cell" error when parsing the missing state selector.
 */
export async function fetchStructureText(
  url: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    const status = `${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
    throw new Error(`Structure request failed (${status})`);
  }
  const text = await response.text();
  if (text.trim().length === 0) {
    throw new Error("Structure response was empty");
  }
  return text;
}

function tuple3(values: readonly number[]): [number, number, number] {
  return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0];
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mql.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

export function useMolstar(opts: Options): Controls {
  const {
    container,
    structureUrl,
    format,
    targetChainIds = NO_CHAINS,
    binderChainIds = NO_CHAINS,
    highlights = NO_HIGHLIGHTS,
    focusHighlightsRequest = 0,
    representation,
    autoRotate = false,
    onCameraChange,
    syncedCamera,
    onResidueClick,
    onResidueHover,
    onStructureLoad,
  } = opts;

  const pluginRef = useRef<unknown>(null);
  const structureRef = useRef<unknown>(null);
  const loadedStructureUrlRef = useRef<string | null>(null);
  const attemptedLoadKeyRef = useRef<string | null>(null);
  const appliedRepresentationRef = useRef<RepresentationStyle | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [structureSummary, setStructureSummary] =
    useState<StructureSummary | null>(null);
  const activeRepresentation =
    representation ?? defaultRepresentation(structureSummary);
  const [structureLoading, setStructureLoading] = useState(false);
  const [loadNonce, setLoadNonce] = useState(0);
  const [camera, setCamera] = useState<CameraState | null>(null);
  const reducedMotion = usePrefersReducedMotion();

  // Keep the latest callback in a ref so the subscription doesn't rewire
  // on every parent re-render.
  const onCameraRef = useRef(onCameraChange);
  useEffect(() => {
    onCameraRef.current = onCameraChange;
  }, [onCameraChange]);
  const onClickRef = useRef(onResidueClick);
  useEffect(() => {
    onClickRef.current = onResidueClick;
  }, [onResidueClick]);
  const onHoverRef = useRef(onResidueHover);
  useEffect(() => {
    onHoverRef.current = onResidueHover;
  }, [onResidueHover]);
  const onStructureLoadRef = useRef(onStructureLoad);
  useEffect(() => {
    onStructureLoadRef.current = onStructureLoad;
  }, [onStructureLoad]);

  /** Mount + unmount. */
  useEffect(() => {
    if (!container) return;
    let cancelled = false;
    let cleanup: (() => void) | undefined;

    (async () => {
      setStatus("loading");
      setError(null);

      // Fail fast on missing WebGL: otherwise Mol* throws an opaque error
      // partway through `createPluginUI` and the user sees a stack trace.
      const gl = detectWebGLSupport();
      if (!gl.ok) {
        setError(gl.reason ?? "WebGL is not available in this browser.");
        setStatus("error");
        return;
      }

      try {
        const [
          { createPluginUI },
          { renderReact18 },
          { DefaultPluginUISpec },
          { PluginConfig },
          { Color },
        ] = await Promise.all([
          import("molstar/lib/mol-plugin-ui/index"),
          import("molstar/lib/mol-plugin-ui/react18"),
          import("molstar/lib/mol-plugin-ui/spec"),
          import("molstar/lib/mol-plugin/config"),
          import("molstar/lib/mol-util/color"),
        ]);

        if (cancelled) return;

        const spec = DefaultPluginUISpec();
        // Strip every Mol* region: Paper Crane renders its own SequencePanel
        // and HOTSPOTS sidebar, so the built-in SequenceView would visually
        // double-up and clash with the paper aesthetic.
        spec.layout = {
          initial: {
            isExpanded: false,
            showControls: false,
            controlsDisplay: "reactive",
            regionState: {
              left: "hidden",
              right: "hidden",
              top: "hidden",
              bottom: "hidden",
            },
          },
        };
        spec.components = {
          ...(spec.components ?? {}),
          remoteState: "none",
          viewport: { view: undefined, controls: undefined },
          controls: {
            top: "none",
            bottom: "none",
            left: "none",
            right: "none",
          },
        };
        spec.config = [
          [PluginConfig.Viewport.ShowAnimation, false],
          [PluginConfig.Viewport.ShowSelectionMode, false],
          [PluginConfig.Viewport.ShowExpand, false],
          [PluginConfig.Viewport.ShowControls, false],
          [PluginConfig.Viewport.ShowSettings, false],
        ];

        const plugin = await createPluginUI({
          target: container,
          render: renderReact18,
          spec,
        });
        if (cancelled) {
          plugin.dispose();
          return;
        }
        pluginRef.current = plugin;

        // Mol* renders selection loci with the renderer's select colour.
        // Match the hotspot legend instead of leaving the default blue/green
        // marker, and keep enough strength for residues to read on graphite.
        plugin.canvas3d?.setProps({
          renderer: {
            backgroundColor: Color(VIEWER_BACKGROUND),
            selectColor: Color(HOTSPOT_COLOR),
            selectStrength: 0.85,
          },
        });

        // Camera subscription.
        const sub = plugin.canvas3d?.didDraw.subscribe(() => {
          const snap = plugin.canvas3d?.camera.getSnapshot();
          if (!snap) return;
          const next: CameraState = {
            position: tuple3(snap.position),
            target: tuple3(snap.target),
            up: tuple3(snap.up),
            radius: snap.radius,
          };
          setCamera(next);
          onCameraRef.current?.(next);
        });

        // Interaction subscriptions (click/hover): lazy imported so
        // residueIdFromMolstarEvent can parse Mol*'s loci payloads. These
        // subscriptions no-op when consumers don't pass callbacks.
        const pluginAny = plugin as unknown as {
          behaviors?: {
            interaction?: {
              click?: {
                subscribe: (fn: (e: unknown) => void) => {
                  unsubscribe: () => void;
                };
              };
              hover?: {
                subscribe: (fn: (e: unknown) => void) => {
                  unsubscribe: () => void;
                };
              };
            };
          };
        };
        const { residueIdFromMolstarEvent } =
          await import("@/lib/viewer/residueSelection");
        const clickSub = pluginAny.behaviors?.interaction?.click?.subscribe(
          (e) => {
            const id = residueIdFromMolstarEvent(e);
            if (id) onClickRef.current?.(id);
          },
        );
        const hoverSub = pluginAny.behaviors?.interaction?.hover?.subscribe(
          (e) => {
            const id = residueIdFromMolstarEvent(e);
            onHoverRef.current?.(id);
          },
        );

        cleanup = () => {
          sub?.unsubscribe();
          clickSub?.unsubscribe();
          hoverSub?.unsubscribe();
          plugin.dispose();
          pluginRef.current = null;
          structureRef.current = null;
          loadedStructureUrlRef.current = null;
          attemptedLoadKeyRef.current = null;
          appliedRepresentationRef.current = null;
        };

        setStatus("ready");
      } catch (e) {
        if (cancelled) return;
        console.error("[Mol*] init failed", e);
        setError(
          e instanceof Error ? e.message : "Failed to initialise viewer",
        );
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [container]);

  /** Load / reload the structure whenever the URL changes. */
  useEffect(() => {
    const plugin = pluginRef.current as {
      clear: () => Promise<void>;
      builders: {
        data: {
          rawData: (args: { data: string; label?: string }) => Promise<unknown>;
        };
        structure: {
          parseTrajectory: (data: unknown, format: string) => Promise<unknown>;
          hierarchy: {
            applyPreset: (traj: unknown, preset: string) => Promise<unknown>;
          };
        };
      };
    } | null;
    if (
      !plugin ||
      !structureUrl ||
      (status !== "ready" && status !== "error") ||
      (status === "ready" && loadedStructureUrlRef.current === structureUrl)
    ) {
      return;
    }
    const loadKey = `${structureUrl}|${format ?? "auto"}|${loadNonce}`;
    if (attemptedLoadKeyRef.current === loadKey) return;
    attemptedLoadKeyRef.current = loadKey;
    let cancelled = false;
    const abortController = new AbortController();

    (async () => {
      setStructureLoading(true);
      setError(null);
      structureRef.current = null;
      try {
        await plugin.clear();
        const fmt = inferFormat(structureUrl, format);
        const text = await fetchStructureText(
          structureUrl,
          abortController.signal,
        );
        if (cancelled) return;
        const data = await plugin.builders.data.rawData({
          data: text,
          label: structureUrl,
        });
        if (cancelled) return;
        const traj = await plugin.builders.structure.parseTrajectory(
          data,
          fmt === "cif" ? "mmcif" : fmt,
        );
        if (cancelled) return;
        const model = await plugin.builders.structure.hierarchy.applyPreset(
          traj,
          "default",
        );
        structureRef.current = model;
        const loadedModel = getLoadedModel(plugin);
        const summary = loadedModel ? summarizeModel(loadedModel) : null;
        const style = representation ?? defaultRepresentation(summary);
        await applyRepresentationStyle(plugin, style);
        appliedRepresentationRef.current = style;
        await applyPaperCranePalette(plugin, {
          targetChainIds,
          binderChainIds,
          highlights,
        });
        onStructureLoadRef.current?.(summary?.chains ?? []);
        // Fit camera to the freshly-loaded structure. The default preset
        // does this once, but re-loads (e.g. switching PDB IDs) need an
        // explicit reset or the camera holds the previous frame. We yield
        // one frame so the new geometry has committed before fitting,
        // otherwise the camera focuses on stale bounds and we get the
        // garbage zoom shown in the bug report.
        try {
          await new Promise<void>((resolve) =>
            requestAnimationFrame(() => resolve()),
          );
          (
            plugin as unknown as {
              managers?: { camera?: { reset: () => void } };
            }
          ).managers?.camera?.reset();
        } catch {
          /* non-fatal */
        }
        if (!cancelled) {
          setStructureSummary(summary);
          loadedStructureUrlRef.current = structureUrl;
          setStructureLoading(false);
          setStatus("ready");
        }
      } catch (e) {
        if (cancelled) return;
        console.error("[Mol*] load failed", e);
        const raw = e instanceof Error ? e.message : String(e);
        // Distinguish: 404 (PDB not found) vs CORS / CSP block vs offline.
        // Mol*'s download helper surfaces the HTTP status as part of the
        // message string; a plain `TypeError: Failed to fetch` is the
        // browser blocking the request (CSP) or the user being offline.
        let friendly: string;
        if (/\b404\b|not found/i.test(raw)) {
          friendly = "PDB not found (404): check the ID";
        } else if (/csp|content security|blocked/i.test(raw)) {
          friendly = "Blocked by browser policy (CSP): contact support";
        } else if (/failed to fetch|networkerror|offline|cors/i.test(raw)) {
          friendly =
            typeof navigator !== "undefined" && navigator.onLine === false
              ? "You're offline: reconnect and retry"
              : "Network error: retry";
        } else {
          friendly = raw || "Failed to load structure";
        }
        setError(friendly);
        loadedStructureUrlRef.current = null;
        setStructureLoading(false);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      abortController.abort();
    };
    // Highlights/chains handled separately below to avoid full reloads on
    // highlight changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, structureUrl, format, loadNonce]);

  /** Re-colour when chain assignments or highlights change. */
  useEffect(() => {
    const plugin = pluginRef.current;
    if (!plugin || status !== "ready" || !structureRef.current) return;
    (async () => {
      try {
        if (appliedRepresentationRef.current !== activeRepresentation) {
          await applyRepresentationStyle(plugin, activeRepresentation);
          appliedRepresentationRef.current = activeRepresentation;
        }
        await applyPaperCranePalette(plugin, {
          targetChainIds,
          binderChainIds,
          highlights,
        });
      } catch (e) {
        console.warn("[Mol*] repaint failed", e);
      }
    })();
  }, [
    status,
    targetChainIds,
    binderChainIds,
    highlights,
    activeRepresentation,
  ]);

  /** Rotation animation. */
  useEffect(() => {
    const plugin = pluginRef.current as {
      canvas3d?: { setProps: (p: unknown) => void };
    } | null;
    if (!plugin?.canvas3d) return;
    const wantRotate = autoRotate && !reducedMotion;
    try {
      plugin.canvas3d.setProps({
        trackball: {
          animate: { name: wantRotate ? "rock" : "off", params: {} },
        },
      });
    } catch {
      /* older Mol* releases name this differently: fail quiet */
    }
  }, [autoRotate, reducedMotion, status]);

  /** Sync external camera (compare mode). */
  useEffect(() => {
    if (!syncedCamera) return;
    const plugin = pluginRef.current as {
      canvas3d?: { camera: { setState: (s: unknown) => void } };
    } | null;
    if (!plugin?.canvas3d) return;
    plugin.canvas3d.camera.setState({
      position: syncedCamera.position,
      target: syncedCamera.target,
      up: syncedCamera.up,
      radius: syncedCamera.radius,
    });
  }, [syncedCamera]);

  const resetCamera = useCallback(() => {
    const plugin = pluginRef.current as {
      managers?: { camera?: { reset: () => void } };
    } | null;
    plugin?.managers?.camera?.reset();
  }, []);

  const retryStructure = useCallback(() => {
    loadedStructureUrlRef.current = null;
    setLoadNonce((value) => value + 1);
  }, []);

  /** Rebuild the hotspot loci, then animate the camera to its exact bounds. */
  useEffect(() => {
    if (
      focusHighlightsRequest <= 0 ||
      status !== "ready" ||
      highlights.length === 0
    ) {
      return;
    }
    const plugin = pluginRef.current;
    if (!plugin || !structureRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        await selectHotspots(plugin, highlights);
        if (cancelled) return;
        const managers = (
          plugin as {
            managers?: {
              structure?: {
                selection?: {
                  elementCount: () => number;
                  getBoundary: () => { sphere: unknown };
                };
              };
              camera?: {
                focusSphere: (
                  sphere: unknown,
                  options?: { durationMs?: number; extraRadius?: number },
                ) => void;
              };
            };
          }
        ).managers;
        const selection = managers?.structure?.selection;
        if (!selection || selection.elementCount() === 0) return;
        managers?.camera?.focusSphere(selection.getBoundary().sphere, {
          durationMs: reducedMotion ? 0 : 450,
          extraRadius: 5,
        });
      } catch (e) {
        console.warn("[Mol*] hotspot focus failed", e);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [focusHighlightsRequest, highlights, reducedMotion, status]);

  const setRepresentation = useCallback((_style: RepresentationStyle) => {
    /* handled via dependency array on applyPaperCranePalette */
  }, []);

  const setAutoRotate = useCallback((_on: boolean) => {
    /* autoRotate is controlled via prop: this is exposed for symmetry */
  }, []);

  const takeScreenshot = useCallback(async (): Promise<string | null> => {
    const plugin = pluginRef.current as {
      helpers?: {
        viewportScreenshot?: {
          getImageDataUri: () => Promise<string>;
        };
      };
      canvas3d?: { webgl?: { gl: WebGLRenderingContext } };
    } | null;
    if (!plugin) return null;
    try {
      if (plugin.helpers?.viewportScreenshot?.getImageDataUri) {
        return await plugin.helpers.viewportScreenshot.getImageDataUri();
      }
    } catch (e) {
      console.warn("[Mol*] screenshot failed", e);
    }
    // Fallback: grab the canvas directly.
    const canvas = container?.querySelector(
      "canvas",
    ) as HTMLCanvasElement | null;
    return canvas?.toDataURL("image/png") ?? null;
  }, [container]);

  return {
    status,
    structureSummary,
    activeRepresentation,
    error,
    structureLoading,
    retryStructure,
    resetCamera,
    setRepresentation,
    setAutoRotate,
    takeScreenshot,
    camera,
    reducedMotion,
  };
}

/**
 * Re-colours the currently loaded structure using Paper Crane's palette and
 * drops hotspot spheres on the target. Kept as a module-level helper so the
 * hook stays readable.
 */
async function applyPaperCranePalette(
  plugin: unknown,
  opts: {
    targetChainIds: string[];
    binderChainIds: string[];
    highlights: DesignHighlight[];
  },
): Promise<void> {
  const p = plugin as {
    managers: {
      structure: {
        hierarchy: {
          current: {
            structures: Array<{
              components: Array<{
                cell: { obj?: { data: { label?: string } } };
                representations: Array<{
                  cell: { transform: { ref: string } };
                }>;
              }>;
            }>;
          };
        };
        component: {
          updateRepresentationsTheme: (
            components: unknown,
            params: unknown,
          ) => Promise<void>;
        };
      };
    };
  };

  const current = p.managers.structure.hierarchy.current.structures[0];
  if (!current) return;

  try {
    const model = getLoadedModel(plugin);
    if (!model) return;
    // Match the chain-id theme's structAsymMap order, including non-polymers.
    const chainIds = [
      ...new Set(
        [...model.properties.structAsymMap.values()].map((v) => v.auth_id),
      ),
    ];
    const color = "chain-id";
    const colorParams = {
      asymId: "auth",
      palette: {
        name: "colors",
        params: {
          list: {
            kind: "set",
            colors: chainIds.map((id, i) =>
              chainColor(i, id, opts.targetChainIds, opts.binderChainIds),
            ),
          },
        },
      },
    };
    await p.managers.structure.component.updateRepresentationsTheme(
      current.components as unknown,
      { color, colorParams },
    );
  } catch (e) {
    console.warn("[Mol*] theme update failed", e);
  }

  // Hotspots are represented through Mol*'s selection loci. Always run the
  // helper, including for an empty list, so removing the final hotspot also
  // clears the old highlight from the canvas.
  try {
    await selectHotspots(plugin, opts.highlights);
  } catch (e) {
    console.warn("[Mol*] hotspot highlight failed", e);
  }
}

/** Replace the visible structure representation instead of only changing UI state. */
async function applyRepresentationStyle(
  plugin: unknown,
  style: RepresentationStyle,
): Promise<void> {
  const p = plugin as {
    managers: {
      structure: {
        hierarchy: {
          current: {
            structures: Array<{ components: unknown[] }>;
          };
        };
        component: {
          removeRepresentations: (
            components: unknown[],
          ) => Promise<void> | undefined;
          addRepresentation: (
            components: unknown[],
            type: string,
          ) => Promise<void> | undefined;
        };
      };
    };
  };
  const components =
    p.managers.structure.hierarchy.current.structures[0]?.components;
  if (!components?.length) return;

  const type =
    style === "atoms"
      ? "ball-and-stick"
      : style === "surface"
        ? "molecular-surface"
        : style === "ribbon"
          ? "backbone"
          : "cartoon";
  await p.managers.structure.component.removeRepresentations(components);
  await p.managers.structure.component.addRepresentation(components, type);
}

async function selectHotspots(
  plugin: unknown,
  highlights: DesignHighlight[],
): Promise<void> {
  const selection = (
    plugin as {
      managers: {
        structure: {
          selection: {
            clear: () => unknown;
            fromSelectionQuery: (mode: string, query: unknown) => Promise<void>;
          };
        };
      };
    }
  ).managers.structure.selection;

  selection.clear();
  if (highlights.length === 0) return;

  const { MolScriptBuilder: MS } =
    await import("molstar/lib/mol-script/language/builder");
  const expression = MS.struct.generator.atomGroups({
    "atom-test": MS.core.logic.or(
      highlights.map((h) =>
        MS.core.logic.and([
          MS.core.rel.eq([MS.ammp("auth_asym_id"), h.chainId]),
          MS.core.rel.eq([MS.ammp("auth_seq_id"), h.resi]),
        ]),
      ),
    ),
  });
  const { StructureSelectionQuery } =
    await import("molstar/lib/mol-plugin-state/helpers/structure-selection-query");
  const query = StructureSelectionQuery("Hotspots", expression);
  await selection.fromSelectionQuery("set", query);
}

/** The model parsed by Mol*, shared by sequence labels and geometry diagnostics. */
function getLoadedModel(plugin: unknown): Model | undefined {
  return (
    plugin as {
      managers: {
        structure: {
          hierarchy: {
            current: {
              structures: Array<{
                cell: { obj?: { data?: { models?: Model[] } } };
              }>;
            };
          };
        };
      };
    }
  ).managers.structure.hierarchy.current.structures[0]?.cell.obj?.data
    ?.models?.[0];
}
