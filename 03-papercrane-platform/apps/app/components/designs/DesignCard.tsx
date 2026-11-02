"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { ResultMetrics } from "./ResultMetrics";
import { toolLabel } from "@/lib/results/metrics";
import { ProvenanceBadge } from "@/components/designs/ProvenanceBadge";

export interface DesignCardData {
  id: string;
  seed: number;
  rank?: number | null;
  tool?: string | null;
  sequence?: string | null;
  length?: number | null;
  /** 'real' | 'synthetic' | 'stub': anything but 'real' is badged. */
  provenance?: string | null;
  metrics: Record<string, number>;
}

export interface DesignCardProps {
  design: DesignCardData;
  href?: string;
  /** When set, the card highlights as if hovered (e.g. driven from scatter). */
  isHighlighted?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

export function DesignCard({ design, href, isHighlighted = false, onMouseEnter, onMouseLeave }: DesignCardProps) {
  return <Link href={href ?? `/app/designs/${design.id}`} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave} className={cn("group block h-full rounded-xl border bg-paper p-5 transition-colors", isHighlighted ? "border-ink" : "border-lattice hover:border-graphite-soft")}>
    <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium text-ink">Seed {design.seed}</span><span className="text-xs text-graphite">{design.length != null ? `${design.length} aa` : ""}</span></div>
    <div className="mt-2 flex items-center gap-2 text-xs text-graphite"><span>{toolLabel(design.tool)}</span><ProvenanceBadge provenance={design.provenance} /></div>
    <div className="mt-5"><ResultMetrics tool={design.tool} metrics={design.metrics} compact /></div>
    {design.sequence && <p className="mt-5 break-all rounded-lg bg-paper-fold/50 p-3 font-mono text-[11px] leading-relaxed text-graphite">{design.sequence.slice(0, 64)}{design.sequence.length > 64 ? "…" : ""}</p>}
    <div className="mt-4 flex items-center justify-end gap-1 pt-3 text-xs text-graphite group-hover:text-ink">Open result <ChevronRight className="h-3 w-3" /></div>
  </Link>;
}
