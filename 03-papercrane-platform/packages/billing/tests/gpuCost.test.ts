import { afterEach, describe, expect, it } from "vitest";
import {
  GPU_PRICE_PER_SECOND_USD,
  DEFAULT_FALLBACK_GPU,
  DEFAULT_COST_SAFETY_MARGIN,
  getCostSafetyMargin,
  estimateJobCost,
  actualCostFromModalSeconds,
} from "../src/gpuCost.js";

/**
 * GPU cost estimation for the private-beta spend cap.
 *
 * Two things must hold for the cap to protect the wallet:
 *   1. Prices match Modal's real per-second rates (no under-counting).
 *   2. The pre-flight estimate rounds UP via a safety margin, while the
 *      post-run reconciliation stays true-cost.
 */

const MARGIN_ENV = "PAPERCRANE_COST_SAFETY_MARGIN";

afterEach(() => {
  delete process.env[MARGIN_ENV];
});

describe("GPU_PRICE_PER_SECOND_USD — real Modal rates", () => {
  it("prices A10 at Modal's real rate (regression: was ~1.9x too low)", () => {
    expect(GPU_PRICE_PER_SECOND_USD.A10).toBe(0.000306);
  });

  it("prices the A100 SKUs distinctly at Modal rates", () => {
    expect(GPU_PRICE_PER_SECOND_USD["A100-40GB"]).toBe(0.000583);
    expect(GPU_PRICE_PER_SECOND_USD["A100-80GB"]).toBe(0.000694);
  });

  it("keys cover the GPU strings the manifests actually declare", () => {
    for (const gpu of ["A10", "L40S", "A100-40GB", "A100-80GB"]) {
      expect(GPU_PRICE_PER_SECOND_USD[gpu]).toBeGreaterThan(0);
    }
  });
});

describe("safety margin", () => {
  it("defaults to 1.4x when env is unset", () => {
    expect(getCostSafetyMargin()).toBe(DEFAULT_COST_SAFETY_MARGIN);
    expect(DEFAULT_COST_SAFETY_MARGIN).toBe(1.4);
  });

  it("honours a valid env override", () => {
    process.env[MARGIN_ENV] = "2";
    expect(getCostSafetyMargin()).toBe(2);
  });

  it("ignores invalid or <1 env values (never under-margins)", () => {
    process.env[MARGIN_ENV] = "0.5";
    expect(getCostSafetyMargin()).toBe(DEFAULT_COST_SAFETY_MARGIN);
    process.env[MARGIN_ENV] = "nonsense";
    expect(getCostSafetyMargin()).toBe(DEFAULT_COST_SAFETY_MARGIN);
  });
});

describe("estimateJobCost", () => {
  it("applies the default margin to the GPU-only total", () => {
    // A100-80GB: 0.000694/s * 100s * 10 seeds = 0.694, * 1.4 margin = 0.9716
    const r = estimateJobCost({
      gpuType: "A100-80GB",
      estSecondsPerDesign: 100,
      numSeeds: 10,
    });
    expect(r.usd.toFixed(4)).toBe("0.9716");
    expect(r.breakdown.safetyMargin).toBe(1.4);
    expect(r.breakdown.fallbackUsed).toBe(false);
  });

  it("drops the margin to exactly GPU cost when env margin is 1", () => {
    process.env[MARGIN_ENV] = "1";
    const r = estimateJobCost({
      gpuType: "A100-80GB",
      estSecondsPerDesign: 100,
      numSeeds: 10,
    });
    expect(r.usd.toFixed(4)).toBe("0.6940");
  });

  it("never under-counts an A10 job (the real wallet risk)", () => {
    const r = estimateJobCost({
      gpuType: "A10",
      estSecondsPerDesign: 100,
      numSeeds: 1,
    });
    expect(r.breakdown.pricePerSecondUsd).toBe(0.000306);
    // GPU-only would be 0.0306; with margin it must be strictly higher.
    expect(Number(r.usd)).toBeGreaterThan(0.000306 * 100 * 1);
  });

  it("falls back to the HIGHEST known rate for an unknown GPU", () => {
    const maxRate = Math.max(...Object.values(GPU_PRICE_PER_SECOND_USD));
    const r = estimateJobCost({
      gpuType: "SomeFutureGPU",
      estSecondsPerDesign: 10,
      numSeeds: 1,
    });
    expect(r.breakdown.fallbackUsed).toBe(true);
    expect(r.breakdown.pricePerSecondUsd).toBe(maxRate);
    expect(r.breakdown.gpuType).toBe(DEFAULT_FALLBACK_GPU);
    // The fallback rate is >= every known rate, so unknowns never under-count.
    for (const rate of Object.values(GPU_PRICE_PER_SECOND_USD)) {
      expect(r.breakdown.pricePerSecondUsd).toBeGreaterThanOrEqual(rate);
    }
  });
});

describe("actualCostFromModalSeconds — true cost, no margin", () => {
  it("does NOT apply the safety margin (reconciliation is real cost)", () => {
    // 0.000694/s * 1000s = 0.694, with NO margin.
    const usd = actualCostFromModalSeconds("A100-80GB", 1000);
    expect(usd?.toFixed(4)).toBe("0.6940");
  });

  it("returns null for an unknown GPU when fallback is disallowed", () => {
    expect(actualCostFromModalSeconds("SomeFutureGPU", 100, false)).toBeNull();
  });
});
