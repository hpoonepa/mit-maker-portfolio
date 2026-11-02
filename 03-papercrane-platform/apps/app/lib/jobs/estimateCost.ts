import type { ToolManifest } from "@papercrane/types";

/**
 * Live cost + seed estimate for a pending job submission.
 *
 * - `seedsRequested` = total seeds the user is dispatching (slider value)
 * - `numDesigns`     = designs per seed; total designs = seeds * numDesigns
 * - `totalSeeds`     = tool.seedCostPerDesign * numDesigns * seedsRequested
 *
 * This mirrors how the scheduler will bill: every design consumes
 * `tool.seedCostPerDesign` seeds from the org quota.
 */
export type CostEstimateInput = {
  tool: Pick<ToolManifest, "seedCostPerDesign" | "compute">;
  /** How many seeds the user has dialed on the slider (1..1000). */
  seedsRequested: number;
  /** How many designs to produce per seed. */
  numDesigns: number;
};

export type CostEstimate = {
  /** Designs actually produced = seeds * designsPerSeed. */
  totalDesigns: number;
  /** Total quota seeds debited from the org (may be 0 for free tools). */
  totalSeeds: number;
  /** Per-design seed cost, echoed back for display. */
  seedCostPerDesign: number;
};

export function estimateCost(input: CostEstimateInput): CostEstimate {
  const seeds = Math.max(0, Math.floor(input.seedsRequested));
  const designs = Math.max(0, Math.floor(input.numDesigns));
  const perDesign = Math.max(0, input.tool.seedCostPerDesign);
  const totalDesigns = seeds * designs;
  const totalSeeds = Math.round(totalDesigns * perDesign * 1000) / 1000;
  return {
    totalDesigns,
    totalSeeds,
    seedCostPerDesign: perDesign,
  };
}

/**
 * True when the projected total exceeds seeds remaining in the period.
 * Use for the submit-button gate and the ToolCompatibilityWarnings panel.
 */
export function exceedsQuota(
  estimate: Pick<CostEstimate, "totalSeeds">,
  remainingSeeds: number,
): boolean {
  return estimate.totalSeeds > Math.max(0, remainingSeeds);
}
