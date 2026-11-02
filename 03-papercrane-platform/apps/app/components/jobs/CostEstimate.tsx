"use client";

import { Clock, Coins, Layers } from "lucide-react";
import type { ToolManifest } from "@papercrane/types";
import type { CostEstimate as CostEstimateShape } from "@/lib/jobs/estimateCost";
import type { EtaEstimate } from "@/lib/jobs/estimateEta";
import { formatEta } from "@/lib/jobs/estimateEta";
import { cn } from "@/lib/utils";

type CostEstimateProps = {
  tool: Pick<ToolManifest, "name" | "compute"> | null;
  cost: CostEstimateShape;
  eta: EtaEstimate;
  /** When true, highlights the total-seeds row in red. */
  overQuota?: boolean;
};

/**
 * Sticky summary card: total designs, total seeds, ETA. Updates live as
 * the user scrubs the slider or switches tools.
 */
export function CostEstimate({ tool, cost, eta, overQuota }: CostEstimateProps) {
  return (
    <aside
      aria-label="Job cost estimate"
      className="p-5"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-sans text-[12px] text-graphite-soft">
          Estimate
        </h3>
        {tool && (
          <span className="font-mono text-[11px] text-graphite-soft truncate max-w-[50%]">
            {tool.name}
          </span>
        )}
      </div>

      <dl className="mt-4 space-y-3">
        <Row
          icon={<Layers className="w-3.5 h-3.5" aria-hidden="true" />}
          label="Designs"
          value={cost.totalDesigns.toLocaleString("en-US")}
        />
        <Row
          icon={<Coins className="w-3.5 h-3.5" aria-hidden="true" />}
          label="Seeds to charge"
          value={formatSeeds(cost.totalSeeds)}
          sub={`${cost.seedCostPerDesign.toFixed(2)} seeds/design`}
          danger={overQuota}
        />
        <Row
          icon={<Clock className="w-3.5 h-3.5" aria-hidden="true" />}
          label="ETA"
          value={formatEta(eta.etaSeconds)}
          sub={
            eta.queueWaitSeconds > 0
              ? `+${formatEta(eta.queueWaitSeconds)} queue`
              : eta.parallelism > 1
                ? `${eta.parallelism}× parallel`
                : undefined
          }
        />
      </dl>

      {cost.totalDesigns === 0 && (
        <p className="mt-4 font-sans text-[12px] text-graphite">
          Pick a tool and set seeds to see the estimate.
        </p>
      )}
    </aside>
  );
}

function Row({
  icon,
  label,
  value,
  sub,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  danger?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="flex items-center gap-2 font-sans text-[13px] text-graphite">
        <span className="text-graphite-soft">{icon}</span>
        {label}
      </dt>
      <dd
        className={cn(
          "text-right",
          danger ? "text-crane-deep" : "text-ink",
        )}
      >
        <div className="font-mono text-[15px] tabular-nums">{value}</div>
        {sub && (
          <div className="font-sans text-[11px] text-graphite-soft">{sub}</div>
        )}
      </dd>
    </div>
  );
}

function formatSeeds(n: number): string {
  if (n === 0) return "0";
  if (n < 1) return n.toFixed(2);
  if (n < 100) return n.toFixed(1).replace(/\.0$/, "");
  return Math.round(n).toLocaleString("en-US");
}
