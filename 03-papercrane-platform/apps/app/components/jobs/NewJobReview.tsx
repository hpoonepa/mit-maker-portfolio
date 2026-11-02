"use client";

import { Clock, Coins, Layers, Target as TargetIcon, Wrench } from "lucide-react";
import type { AllocationStrategy } from "@/lib/jobs/allocation";
import type { CostEstimate as CostEstimateShape } from "@/lib/jobs/estimateCost";
import { formatEta } from "@/lib/jobs/estimateEta";

export interface NewJobReviewRow {
  toolId: string;
  name: string;
  count: number;
}

export interface NewJobReviewProps {
  targetName: string;
  targetSub?: string;
  rows: NewJobReviewRow[];
  cost: CostEstimateShape;
  etaSeconds: number;
  strategy: AllocationStrategy;
  runNoun?: string;
  /** Tool names that failed to submit on the last Run attempt. */
  failedTools?: string[];
}

/**
 * Read-only step-4 summary: target, per-tool design counts, and aggregate
 * cost + ETA. Purely presentational; the parent owns the Run action.
 */
export function NewJobReview({
  targetName,
  targetSub,
  rows,
  cost,
  etaSeconds,
  runNoun = "designs",
  failedTools = [],
}: NewJobReviewProps): JSX.Element {
  const multi = rows.length > 1;
  return (
    <div className="mx-auto max-w-5xl space-y-5" data-testid="e2e-job-review">
      {failedTools.length > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep"
        >
          Couldn&apos;t submit {failedTools.join(", ")}. Nothing was queued -
          adjust and run again.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
        <div className="overflow-hidden bg-paper/65">
          <div className="px-0">
            <ManifestRow
              icon={<TargetIcon className="h-4 w-4" />}
              label="Target"
              value={targetName}
              sub={targetSub && targetSub !== targetName ? targetSub : undefined}
            />
            <div className="py-4">
              <div className="mb-3 flex items-center gap-2 font-sans text-[12px] text-graphite-soft">
                <Wrench className="h-4 w-4" />
                {multi ? "Tools & allocation" : "Tool"}
              </div>
              <ul className="space-y-2">
                {rows.map((row) => (
                  <li
                    key={row.toolId}
                    className="flex items-center justify-between gap-4 py-2"
                  >
                    <span className="min-w-0 truncate font-sans text-[14px] text-ink">
                      {row.name}
                    </span>
                    <span
                      data-testid={`e2e-job-review-count-${row.toolId}`}
                      className="font-mono text-[11px] tabular-nums text-graphite"
                    >
                      {row.count.toLocaleString("en-US")} {row.count === 1 ? runNoun.replace(/s$/, "") : runNoun}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="bg-paper/65 p-5">
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Stat
              icon={<Layers className="h-4 w-4" />}
              label={runNoun.charAt(0).toUpperCase() + runNoun.slice(1)}
              value={cost.totalDesigns.toLocaleString("en-US")}
            />
            <Stat
              icon={<Coins className="h-4 w-4" />}
              label="Seeds"
              value={cost.totalSeeds.toLocaleString("en-US")}
            />
          </div>
          <div className="mt-3 py-4">
            <div className="flex items-center gap-2 font-sans text-[12px] text-crane-deep">
              <Clock className="h-4 w-4" />
              Expected runtime
            </div>
            <p className="mt-2 font-mono text-[24px] tabular-nums text-ink">
              {formatEta(etaSeconds)}
            </p>
            <p className="mt-1 font-sans text-[11px] leading-relaxed text-graphite-soft">
              {multi
                ? `${rows.length} tools run in parallel. Live progress opens next.`
                : "Live progress opens next. You can safely leave once queued."}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ManifestRow({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex items-start gap-3 py-4">
      <span className="mt-0.5 text-graphite-soft">{icon}</span>
      <div className="min-w-0">
        <p className="font-sans text-[12px] text-graphite-soft">
          {label}
        </p>
        <p className="mt-1 font-sans text-[15px] text-ink">{value}</p>
        {sub && (
          <p className="mt-0.5 font-mono text-[11px] text-graphite-soft">
            {sub}
          </p>
        )}
      </div>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="p-3.5">
      <div className="flex items-center gap-2 font-sans text-[9px] text-graphite-soft">
        <span className="text-graphite-soft">{icon}</span>
        {label}
      </div>
      <div className="mt-2 font-mono text-[18px] tabular-nums text-ink">
        {value}
      </div>
    </div>
  );
}
