import { describe, it, expect } from "vitest";
import type { ToolManifest } from "@papercrane/types";
import { estimateCost, exceedsQuota } from "./estimateCost.js";

const rfd: Pick<ToolManifest, "seedCostPerDesign" | "compute"> = {
  seedCostPerDesign: 0.25,
  compute: {
    gpuType: "A100",
    gpuCount: 1,
    memoryGb: 80,
    estimatedMinutes: 2,
  },
};

const freeTool: Pick<ToolManifest, "seedCostPerDesign" | "compute"> = {
  seedCostPerDesign: 0,
  compute: {
    gpuType: "T4",
    gpuCount: 1,
    memoryGb: 16,
    estimatedMinutes: 0.5,
  },
};

describe("estimateCost", () => {
  it("returns 0 for empty seeds", () => {
    const est = estimateCost({ tool: rfd, seedsRequested: 0, numDesigns: 10 });
    expect(est.totalDesigns).toBe(0);
    expect(est.totalSeeds).toBe(0);
  });

  it("multiplies seeds × designs × seedCostPerDesign", () => {
    const est = estimateCost({ tool: rfd, seedsRequested: 8, numDesigns: 16 });
    expect(est.totalDesigns).toBe(128);
    expect(est.totalSeeds).toBe(32); // 128 * 0.25
    expect(est.seedCostPerDesign).toBe(0.25);
  });

  it("handles free-tier tools with 0 seed cost", () => {
    const est = estimateCost({ tool: freeTool, seedsRequested: 100, numDesigns: 4 });
    expect(est.totalDesigns).toBe(400);
    expect(est.totalSeeds).toBe(0);
  });

  it("floors fractional slider inputs", () => {
    const est = estimateCost({
      tool: rfd,
      seedsRequested: 7.9,
      numDesigns: 4.4,
    });
    expect(est.totalDesigns).toBe(7 * 4);
  });

  it("rounds to 3 decimals to avoid IEEE drift", () => {
    const est = estimateCost({
      tool: { ...rfd, seedCostPerDesign: 0.1 },
      seedsRequested: 3,
      numDesigns: 1,
    });
    expect(est.totalSeeds).toBeCloseTo(0.3, 5);
  });

  it("clamps negative inputs to 0", () => {
    const est = estimateCost({ tool: rfd, seedsRequested: -5, numDesigns: -3 });
    expect(est.totalDesigns).toBe(0);
    expect(est.totalSeeds).toBe(0);
  });
});

describe("exceedsQuota", () => {
  it("is true when total > remaining", () => {
    expect(exceedsQuota({ totalSeeds: 100 }, 50)).toBe(true);
  });
  it("is false when equal", () => {
    expect(exceedsQuota({ totalSeeds: 50 }, 50)).toBe(false);
  });
  it("is false when zero-cost even if quota is 0", () => {
    expect(exceedsQuota({ totalSeeds: 0 }, 0)).toBe(false);
  });
  it("treats negative remaining as 0", () => {
    expect(exceedsQuota({ totalSeeds: 1 }, -10)).toBe(true);
  });
});
