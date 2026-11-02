import { describe, it, expect } from "vitest";
import type { ToolManifest } from "@papercrane/types";
import { estimateEta, formatEta } from "./estimateEta.js";

const singleGpu: Pick<ToolManifest, "compute"> = {
  compute: {
    gpuType: "A100",
    gpuCount: 1,
    memoryGb: 80,
    estimatedMinutes: 2, // 120s per design
  },
};

const quadGpu: Pick<ToolManifest, "compute"> = {
  compute: {
    gpuType: "H100",
    gpuCount: 4,
    memoryGb: 80,
    estimatedMinutes: 1, // 60s per design
  },
};

describe("estimateEta", () => {
  it("is 0 run-time for 0 designs but still includes queue wait", () => {
    const eta = estimateEta({
      tool: singleGpu,
      totalDesigns: 0,
      queueDepth: 2,
      avgQueueJobSeconds: 90,
    });
    expect(eta.runSeconds).toBe(0);
    expect(eta.queueWaitSeconds).toBe(180);
    expect(eta.etaSeconds).toBe(180);
  });

  it("uses the worker's two-lane default on a GPU tool", () => {
    const eta = estimateEta({ tool: singleGpu, totalDesigns: 5 });
    // ceil(5 designs / 2 lanes) * 120s = 360s
    expect(eta.runSeconds).toBe(360);
    expect(eta.parallelism).toBe(2);
    expect(eta.etaSeconds).toBe(360);
  });

  it("fans out on multi-GPU tool by gpuCount", () => {
    const eta = estimateEta({ tool: quadGpu, totalDesigns: 8 });
    // 8 designs / 4 GPUs = 2 passes * 60s = 120s
    expect(eta.runSeconds).toBe(120);
    expect(eta.parallelism).toBe(4);
  });

  it("rounds uneven batches up (ceil), not truncating work", () => {
    const eta = estimateEta({ tool: quadGpu, totalDesigns: 9 });
    // ceil(9/4) = 3 passes * 60s = 180s
    expect(eta.runSeconds).toBe(180);
  });

  it("adds queue depth * avg job time", () => {
    const eta = estimateEta({
      tool: singleGpu,
      totalDesigns: 2,
      queueDepth: 3,
      avgQueueJobSeconds: 60,
    });
    // queue: 3*60=180, run: one two-seed wave at 120s
    expect(eta.queueWaitSeconds).toBe(180);
    expect(eta.runSeconds).toBe(120);
    expect(eta.etaSeconds).toBe(300);
  });

  it("honors parallelism override", () => {
    const eta = estimateEta({
      tool: singleGpu,
      totalDesigns: 4,
      parallelism: 2,
    });
    expect(eta.runSeconds).toBe(240); // ceil(4/2) * 120
  });

  it("clamps parallelism to >=1", () => {
    const eta = estimateEta({
      tool: singleGpu,
      totalDesigns: 2,
      parallelism: 0,
    });
    expect(eta.parallelism).toBe(1);
  });
});

describe("formatEta", () => {
  it("formats sub-minute as < 1m", () => {
    expect(formatEta(30)).toBe("< 1m");
    expect(formatEta(0)).toBe("< 1m");
  });
  it("formats minutes when < 60m", () => {
    expect(formatEta(600)).toBe("10m");
    expect(formatEta(3540)).toBe("59m");
  });
  it("formats hours with no leftover minutes", () => {
    expect(formatEta(3600)).toBe("1h");
    expect(formatEta(7200)).toBe("2h");
  });
  it("formats hours + minutes", () => {
    expect(formatEta(3600 + 720)).toBe("1h 12m");
    expect(formatEta(2 * 3600 + 30 * 60)).toBe("2h 30m");
  });
});
