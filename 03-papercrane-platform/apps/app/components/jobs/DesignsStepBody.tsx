"use client";

import type { ToolManifest } from "@papercrane/types";
import { StepIntro } from "./StepIntro";
import { SeedAllocator } from "./SeedAllocator";
import { AllocationControl } from "./AllocationControl";
import { CostEstimate } from "./CostEstimate";
import type { AllocationStrategy } from "@/lib/jobs/allocation";
import type { EtaEstimate } from "@/lib/jobs/estimateEta";

export interface DesignsStepBodyProps {
  /** "designs" | "predictions" | "runs": depends on what the tools do. */
  runNounPlural: string;
  selectedToolIds: string[];
  selectedTools: ToolManifest[];
  toolNameMap: Record<string, string>;

  totalDesigns: number;
  onTotalDesignsChange: (n: number) => void;
  strategy: AllocationStrategy;
  onStrategyChange: (s: AllocationStrategy) => void;
  manualCounts: Record<string, number>;
  onManualChange: (toolId: string, value: number) => void;
  perToolCounts: Record<string, number>;

  remainingSeeds?: number;
  seedsConsumed?: number;
  seedsIncluded?: number;
  overQuota: boolean;

  cost: { totalDesigns: number; totalSeeds: number; seedCostPerDesign: number };
  eta: EtaEstimate;
}

/**
 * The wizard's "how much to run" step: a count, an optional split across
 * tools when several are selected, and the live seed/ETA estimate beside it.
 */
export function DesignsStepBody({
  runNounPlural,
  selectedToolIds,
  selectedTools,
  toolNameMap,
  totalDesigns,
  onTotalDesignsChange,
  strategy,
  onStrategyChange,
  manualCounts,
  onManualChange,
  perToolCounts,
  remainingSeeds,
  seedsConsumed,
  seedsIncluded,
  overQuota,
  cost,
  eta,
}: DesignsStepBodyProps) {
  const multi = selectedToolIds.length >= 2;
  const title = `How many ${runNounPlural}?`;
  const only = selectedTools.length === 1 ? selectedTools[0] : null;

  return (
    <div className="space-y-6">
      <StepIntro
        title={title}
        sub={
          multi
            ? "Set a total, then split it across your selected tools. More runs use more compute."
            : "Start with one, or run several to compare results. More runs use more compute."
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_280px] lg:items-start">
        <div className="space-y-6">
          <div className="space-y-3">
            <SeedAllocator
              label={multi ? `Total ${runNounPlural}` : `Number of ${runNounPlural}`}
              seeds={totalDesigns}
              onChange={onTotalDesignsChange}
              min={1}
              max={1000}
              remaining={remainingSeeds}
              consumed={seedsConsumed}
              included={seedsIncluded}
              error={
                overQuota
                  ? `That's more ${runNounPlural} than the seeds left in your current period. Lower the number, or wait for the period to reset.`
                  : undefined
              }
            />
            {only?.toolId === "boltzgen" && (
              <p className="font-sans text-[12px] leading-relaxed text-graphite">
                For a quick test or demo, run 1 design. BoltzGen completes each
                design as a full GPU workflow, so larger batches cost more.
              </p>
            )}
          </div>

          {multi && (
            <AllocationControl
              toolIds={selectedToolIds}
              toolNames={toolNameMap}
              totalDesigns={totalDesigns}
              strategy={strategy}
              onStrategyChange={onStrategyChange}
              manualCounts={manualCounts}
              onManualChange={onManualChange}
              perToolCounts={perToolCounts}
            />
          )}
        </div>

        <CostEstimate
          tool={only ? { name: only.name, compute: only.compute } : null}
          cost={cost}
          eta={eta}
          overQuota={overQuota}
        />
      </div>
    </div>
  );
}
