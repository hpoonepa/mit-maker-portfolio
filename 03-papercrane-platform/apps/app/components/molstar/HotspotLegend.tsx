"use client";

/**
 * HotspotLegend: small color key that explains what the residue colors in
 * the 3D viewer mean.
 *
 * Three rows:
 *   1. The strength gradient (warm → deep) when multiple hotspots are picked.
 *   2. The pink "selected" highlight (single click).
 *   3. The graphite "target" base color.
 *
 * Compact by default; render it next to the viewer or inside an info panel.
 */
import { cn } from "@/lib/utils";

export interface HotspotLegendProps {
  /** Hide the gradient row when only zero/one hotspot is selected. */
  showGradient?: boolean;
  /** Number of currently-selected residues: drives the count badge. */
  count?: number;
  className?: string;
}

export function HotspotLegend({
  showGradient = true,
  count,
  className,
}: HotspotLegendProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-lattice bg-paper-fold/60 p-3",
        className,
      )}
      role="group"
      aria-label="Viewer color legend"
    >
      <div className="flex items-center justify-between">
        <p className="font-sans text-[12px] text-graphite-soft">
          Legend
        </p>
        {typeof count === "number" && (
          <span
            className="rounded-full border border-lattice bg-paper px-2 py-0.5 font-mono text-[10px] text-ink tabular-nums"
            aria-label={`${count} hotspots selected`}
          >
            {count} picked
          </span>
        )}
      </div>

      <ul className="mt-2 flex flex-col gap-1.5">
        <li className="flex items-center gap-2">
          <span
            aria-hidden
            className="h-3 w-3 rounded-full ring-1 ring-inset ring-black/10"
            style={{ backgroundColor: "#5A554D" }}
          />
          <span className="font-sans text-[12px] text-graphite">Target</span>
        </li>
        <li className="flex items-center gap-2">
          <span
            aria-hidden
            className="h-3 w-3 rounded-full ring-1 ring-inset ring-black/10"
            style={{ backgroundColor: "#FF7AB6" }}
          />
          <span className="font-sans text-[12px] text-graphite">
            Selected residue
          </span>
        </li>
        {showGradient && (
          <li className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-3 w-12 rounded-full ring-1 ring-inset ring-black/10"
              style={{
                background:
                  "linear-gradient(90deg, rgb(255,234,196) 0%, rgb(193,39,45) 100%)",
              }}
            />
            <span className="font-sans text-[12px] text-graphite">
              Hotspot strength{" "}
              <span className="font-mono text-[10px] text-graphite-soft">
                low → high
              </span>
            </span>
          </li>
        )}
      </ul>
    </div>
  );
}

export default HotspotLegend;
