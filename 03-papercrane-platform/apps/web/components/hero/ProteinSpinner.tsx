"use client";

/**
 * Hero protein spinner — a slow, hypnotic Mol* viewer.
 *
 * Loads 6X1A (an iGEM-flavoured fluorescent protein) from RCSB by default,
 * renders cartoon coloured by chain, auto-rotates ~1 deg/sec, and links to
 * /signup on click. The whole Mol* import chain is dynamic so the heavy
 * (~2 MB gz) bundle never lands in the initial landing-page payload.
 *
 * If WebGL is unavailable (or the runtime crashes before `ready`) we fall
 * back to an animated SVG protein silhouette — visceral enough that the page
 * never looks broken.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getAppUrl } from "@/lib/links";

type Status = "idle" | "loading" | "ready" | "error";

interface ProteinSpinnerProps {
  /** RCSB PDB id. */
  pdbId?: string;
  /** Anchor used in the /signup query string for attribution. */
  source?: string;
  className?: string;
}

const RCSB_URL = (id: string) =>
  `https://files.rcsb.org/download/${id.toUpperCase()}.cif`;

function detectWebGL(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return !!(
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl")
    );
  } catch {
    return false;
  }
}

export function ProteinSpinner({
  pdbId = "6X1A",
  source = "landing-spinner",
  className,
}: ProteinSpinnerProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const appUrl = getAppUrl();
  const signupHref = `${appUrl}/signup?source=${encodeURIComponent(source)}`;

  const handleClick = useCallback(() => {
    if (typeof window === "undefined") return;
    window.location.href = signupHref;
  }, [signupHref]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    if (!detectWebGL()) {
      setStatus("error");
      return;
    }
    let cancelled = false;
    let cleanup: (() => void) | undefined;

    (async () => {
      setStatus("loading");
      try {
        const [
          { createPluginUI },
          { renderReact18 },
          { DefaultPluginUISpec },
          { PluginConfig },
        ] = await Promise.all([
          import("molstar/lib/mol-plugin-ui/index"),
          import("molstar/lib/mol-plugin-ui/react18"),
          import("molstar/lib/mol-plugin-ui/spec"),
          import("molstar/lib/mol-plugin/config"),
        ]);
        if (cancelled) return;

        const spec = DefaultPluginUISpec();
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
          target: host,
          render: renderReact18,
          spec,
        });
        if (cancelled) {
          plugin.dispose();
          return;
        }

        const builders = (
          plugin as unknown as {
            builders: {
              data: {
                download: (a: {
                  url: string;
                  isBinary: boolean;
                }) => Promise<unknown>;
              };
              structure: {
                parseTrajectory: (
                  data: unknown,
                  format: string,
                ) => Promise<unknown>;
                hierarchy: {
                  applyPreset: (
                    traj: unknown,
                    preset: string,
                  ) => Promise<unknown>;
                };
              };
            };
          }
        ).builders;

        const data = await builders.data.download({
          url: RCSB_URL(pdbId),
          isBinary: false,
        });
        if (cancelled) return;
        const traj = await builders.structure.parseTrajectory(data, "mmcif");
        if (cancelled) return;
        await builders.structure.hierarchy.applyPreset(traj, "default");
        if (cancelled) return;

        // Slow, continuous spin around the vertical axis (~1 deg/sec).
        try {
          (
            plugin as unknown as {
              canvas3d?: { setProps: (p: unknown) => void };
            }
          ).canvas3d?.setProps({
            trackball: {
              animate: {
                name: "spin",
                params: { speed: 0.17 },
              },
            },
          });
        } catch {
          /* older Mol* releases may name this differently — fail quiet */
        }

        try {
          (
            plugin as unknown as {
              managers?: { camera?: { reset: () => void } };
            }
          ).managers?.camera?.reset();
        } catch {
          /* non-fatal */
        }

        setStatus("ready");
        cleanup = () => {
          try {
            plugin.dispose();
          } catch {
            /* noop */
          }
        };
      } catch (err) {
        if (cancelled) return;
        console.warn("[ProteinSpinner] Mol* init failed", err);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [pdbId]);

  const isError = status === "error";

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={`Spinning ${pdbId} protein structure — click to start free`}
      className={[
        "group relative block w-full h-full aspect-square rounded-[14px]",
        "border border-lattice bg-paper-fold/40 overflow-hidden",
        "transition-colors duration-300",
        "hover:border-crane/60 cursor-pointer",
        "focus:outline-none focus:ring-2 focus:ring-crane/60 focus:ring-offset-2 focus:ring-offset-paper",
        className ?? "",
      ].join(" ")}
    >
      {/* Mol* host. We always mount the host so the plugin has a target;
          the SVG fallback overlays it on error. */}
      <div
        ref={hostRef}
        aria-hidden="true"
        className="absolute inset-0 [&>div]:!bg-transparent"
        style={{ background: "transparent" }}
      />

      {/* Loading shimmer */}
      {(status === "idle" || status === "loading") && !isError && (
        <div
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
        >
          <div className="flex flex-col items-center gap-3">
            <div className="h-12 w-12 animate-spin rounded-full border-2 border-crane/25 border-t-crane" />
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-graphite-soft">
              Folding {pdbId}…
            </span>
          </div>
        </div>
      )}

      {/* Fallback SVG silhouette */}
      {isError && <SpinnerFallback />}

      {/* Hover affordance */}
      <div
        aria-hidden="true"
        className="absolute bottom-4 right-4 flex items-center gap-2 rounded-full bg-paper/85 px-3 py-1.5 backdrop-blur-sm border border-lattice transition-all opacity-0 group-hover:opacity-100 group-hover:translate-y-0 translate-y-1"
      >
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink">
          Start free
        </span>
        <span className="text-crane text-[12px]">→</span>
      </div>

      {/* PDB attribution */}
      <div
        aria-hidden="true"
        className="absolute top-4 left-4 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-graphite-soft"
      >
        <span className="crane-dot opacity-70" />
        PDB · {pdbId}
      </div>
    </button>
  );
}

/**
 * Animated SVG protein silhouette. Used when WebGL is unavailable or Mol*
 * fails to initialise. A slow, looping rotation keeps the visual energy of
 * the live spinner.
 */
function SpinnerFallback() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-paper-fold/30">
      <svg
        viewBox="0 0 200 200"
        className="w-3/4 h-3/4"
        style={{
          animation: "spin 24s linear infinite",
          transformOrigin: "50% 50%",
        }}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="ps-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#C1272D" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#5A554D" stopOpacity="0.7" />
          </linearGradient>
        </defs>
        {/* Stylised double-helix-ish ribbon */}
        <g fill="none" stroke="url(#ps-grad)" strokeWidth="3" strokeLinecap="round">
          <path d="M40 100 Q 70 40, 100 100 T 160 100" />
          <path d="M40 100 Q 70 160, 100 100 T 160 100" />
          <path d="M55 100 Q 80 55, 100 100 T 145 100" opacity="0.55" />
          <path d="M55 100 Q 80 145, 100 100 T 145 100" opacity="0.55" />
        </g>
        {/* Residue dots */}
        {[40, 60, 80, 100, 120, 140, 160].map((cx) => (
          <circle key={cx} cx={cx} cy="100" r="3" fill="#C1272D" opacity="0.7" />
        ))}
      </svg>
    </div>
  );
}

export default ProteinSpinner;
