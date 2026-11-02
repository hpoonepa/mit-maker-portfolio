"use client";

/**
 * HotspotChip: pill-shaped affordance for a single selected residue.
 *
 * Renders the chain + residue number in mono ("A:42") with a colored dot
 * showing where the residue sits on the strength gradient (used when
 * residues are colored by hotspot rank in the 3D viewer). Click X to
 * remove the residue from the selection.
 */
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface HotspotChipProps {
  chain: string;
  resi: number;
  /** 0..1 position on the strength gradient (driven by selection rank). */
  strength?: number;
  /** Highlights the chip (e.g. matches the residue currently hovered in 3D). */
  active?: boolean;
  /** Removes the residue. */
  onRemove?: () => void;
  /** Click handler for the body: typically pans the 3D camera to the residue. */
  onClick?: () => void;
}

/**
 * Linear interpolation between the picker's two brand stops:
 *   strength 0 → crane-glow (warm cream)
 *   strength 1 → crane-deep (deep red)
 */
function strengthToColor(strength: number): string {
  const s = Math.max(0, Math.min(1, strength));
  // crane-glow ≈ rgb(255, 234, 196), crane-deep ≈ rgb(193, 39, 45)
  const r = Math.round(255 + (193 - 255) * s);
  const g = Math.round(234 + (39 - 234) * s);
  const b = Math.round(196 + (45 - 196) * s);
  return `rgb(${r}, ${g}, ${b})`;
}

export function HotspotChip({
  chain,
  resi,
  strength = 0.5,
  active = false,
  onRemove,
  onClick,
}: HotspotChipProps) {
  const color = strengthToColor(strength);
  return (
    <span
      className={cn(
        "group inline-flex items-center gap-1.5 rounded-full border bg-paper px-2.5 py-1 font-mono text-[12px] text-ink transition-colors",
        active
          ? "border-crane-deep ring-1 ring-crane-deep/40"
          : "border-lattice-strong hover:border-ink",
      )}
      data-chain={chain}
      data-resi={resi}
      role="listitem"
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full ring-1 ring-inset ring-black/10"
        style={{ backgroundColor: color }}
      />
      <button
        type="button"
        onClick={onClick}
        className="tabular-nums tracking-tight outline-none focus:underline"
        aria-label={`Focus residue ${chain}:${resi}`}
        title={`Focus residue ${chain}:${resi}`}
      >
        {chain}:{resi}
      </button>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="-mr-1 ml-0.5 rounded-full p-0.5 text-graphite-soft transition-colors hover:bg-paper-fold hover:text-ink"
          aria-label={`Remove residue ${chain}:${resi}`}
          title="Remove (or Cmd-click in viewer)"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}

export default HotspotChip;
