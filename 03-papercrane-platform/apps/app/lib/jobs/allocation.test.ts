import { describe, it, expect } from "vitest";
import {
  allocate,
  manualSumValid,
  TOOL_WEIGHT_PRIOR,
  type AllocateOpts,
} from "./allocation.js";

const sum = (rec: Record<string, number>) =>
  Object.values(rec).reduce((a, b) => a + b, 0);

describe("allocate: even strategy", () => {
  it("splits evenly when divisible", () => {
    const out = allocate({
      strategy: "even",
      totalDesigns: 12,
      toolIds: ["a", "b", "c"],
    });
    expect(out).toEqual({ a: 4, b: 4, c: 4 });
  });

  it("distributes remainder +1 to the first tools by stable order", () => {
    const out = allocate({
      strategy: "even",
      totalDesigns: 10,
      toolIds: ["a", "b", "c"],
    });
    // floor(10/3)=3 each (9), remainder 1 -> first tool gets +1
    expect(out).toEqual({ a: 4, b: 3, c: 3 });
    expect(sum(out)).toBe(10);
  });

  it("distributes remainder of 2 to the first two tools", () => {
    const out = allocate({
      strategy: "even",
      totalDesigns: 11,
      toolIds: ["a", "b", "c"],
    });
    expect(out).toEqual({ a: 4, b: 4, c: 3 });
    expect(sum(out)).toBe(11);
  });
});

describe("allocate: auto strategy", () => {
  it("falls back to an even split when no tool has a prior", () => {
    const out = allocate({
      strategy: "auto",
      totalDesigns: 10,
      toolIds: ["unknown1", "unknown2", "unknown3"],
      weightPrior: {},
    });
    // all neutral weight 1 => same shape as even split
    expect(out).toEqual({ unknown1: 4, unknown2: 3, unknown3: 3 });
    expect(sum(out)).toBe(10);
  });

  it("weights by prior, normalizes, and sums EXACTLY to total via largest-remainder", () => {
    const out = allocate({
      strategy: "auto",
      totalDesigns: 10,
      toolIds: ["bindcraft", "boltz2"],
    });
    // bindcraft prior > boltz2 prior => bindcraft gets the larger share
    expect(sum(out)).toBe(10);
    expect(out.bindcraft).toBeGreaterThan(out.boltz2!);
    expect(out.bindcraft).toBeGreaterThanOrEqual(1);
    expect(out.boltz2).toBeGreaterThanOrEqual(1);
  });

  it("guarantees every tool gets >= 1 (when total >= tool count) and sums exactly", () => {
    const toolIds = ["bindcraft", "rfdiffusion", "proteinmpnn", "boltz2"];
    for (const total of [4, 5, 7, 13, 50, 97]) {
      const out = allocate({ strategy: "auto", totalDesigns: total, toolIds });
      expect(sum(out)).toBe(total);
      for (const id of toolIds) {
        expect(out[id]).toBeGreaterThanOrEqual(1);
      }
    }
  });

  it("includes every toolId as a key", () => {
    const out = allocate({
      strategy: "auto",
      totalDesigns: 20,
      toolIds: ["bindcraft", "chai1", "ligandmpnn"],
    });
    expect(Object.keys(out).sort()).toEqual(
      ["bindcraft", "chai1", "ligandmpnn"].sort(),
    );
  });
});

describe("allocate: single tool", () => {
  it.each<AllocateOpts["strategy"]>(["auto", "even"])(
    "gives all designs to the only tool (%s)",
    (strategy) => {
      const out = allocate({
        strategy,
        totalDesigns: 50,
        toolIds: ["bindcraft"],
      });
      expect(out).toEqual({ bindcraft: 50 });
    },
  );
});

describe("allocate: manual strategy", () => {
  it("returns the manual counts as-is with every toolId present", () => {
    const out = allocate({
      strategy: "manual",
      totalDesigns: 10,
      toolIds: ["a", "b"],
      manualCounts: { a: 3, b: 7 },
    });
    expect(out).toEqual({ a: 3, b: 7 });
  });

  it("defaults missing tool keys to 0", () => {
    const out = allocate({
      strategy: "manual",
      totalDesigns: 10,
      toolIds: ["a", "b", "c"],
      manualCounts: { a: 10 },
    });
    expect(out).toEqual({ a: 10, b: 0, c: 0 });
  });
});

describe("manualSumValid", () => {
  it("is true when counts sum exactly to total", () => {
    expect(manualSumValid({ a: 3, b: 7 }, ["a", "b"], 10)).toBe(true);
  });

  it("is false when counts under-sum", () => {
    expect(manualSumValid({ a: 3, b: 6 }, ["a", "b"], 10)).toBe(false);
  });

  it("is false when counts over-sum", () => {
    expect(manualSumValid({ a: 5, b: 7 }, ["a", "b"], 10)).toBe(false);
  });

  it("treats missing keys as 0", () => {
    expect(manualSumValid({ a: 10 }, ["a", "b"], 10)).toBe(true);
  });

  it("is false when any count is negative even if the sum matches", () => {
    expect(manualSumValid({ a: 12, b: -2 }, ["a", "b"], 10)).toBe(false);
  });
});

describe("TOOL_WEIGHT_PRIOR", () => {
  it("seeds priors for the known tool slugs", () => {
    for (const slug of [
      "bindcraft",
      "rfdiffusion",
      "proteinmpnn",
      "boltz2",
      "chai1",
      "boltzgen",
      "ligandmpnn",
      "solublempnn",
    ]) {
      expect(TOOL_WEIGHT_PRIOR[slug]).toBeGreaterThan(0);
    }
  });
});
