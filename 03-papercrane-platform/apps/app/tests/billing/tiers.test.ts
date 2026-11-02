import { describe, it, expect } from "vitest";
import {
  TIERS,
  getTier,
  listFeatures,
  compareFeature,
  PRO_MONTHLY_PRICE_USD,
  PRO_ANNUAL_PRICE_USD,
  annualSavingsPercent,
} from "@/lib/billing/tiers";

/**
 * Feature matrix is the contract between the UpgradeModal, the
 * CurrentPlanCard, and any future pricing-table surface. These tests pin
 * down the shape + a few load-bearing values so a refactor doesn't silently
 * drop a feature row.
 *
 * We deliberately DON'T cross-check numbers against
 * `@papercrane/billing`'s tier flags here: the UI copy intentionally
 * diverges (e.g. "unlimited" vs a raw cap). Billing package tests own the
 * enforcement side.
 */

describe("tiers: feature matrix", () => {
  it("exposes free, pro, and frontier tiers", () => {
    expect(TIERS.map((t) => t.id)).toEqual(["free", "pro", "frontier"]);
  });

  it("getTier returns the tier definition by id", () => {
    const pro = getTier("pro");
    expect(pro.id).toBe("pro");
    expect(pro.name).toBe("Pro");
    expect(pro.monthlyPriceUsd).toBe(PRO_MONTHLY_PRICE_USD);
    expect(pro.annualPriceUsd).toBe(PRO_ANNUAL_PRICE_USD);
  });

  it("listFeatures returns one row per feature, with a value per tier", () => {
    const rows = listFeatures();
    expect(rows.length).toBeGreaterThan(3);
    for (const row of rows) {
      expect(row).toHaveProperty("label");
      expect(row.values).toHaveProperty("free");
      expect(row.values).toHaveProperty("pro");
      expect(row.values).toHaveProperty("frontier");
    }
  });

  it("compareFeature picks the value for a specific tier", () => {
    const seeds = compareFeature("seedsPerMonth", "pro");
    expect(seeds).toBe("50,000");
    const concurrent = compareFeature("maxConcurrent", "free");
    expect(concurrent).toBe("2");
  });

  it("annual price saves at least 15% vs paying monthly", () => {
    const savings = annualSavingsPercent();
    expect(savings).toBeGreaterThanOrEqual(15);
    expect(savings).toBeLessThanOrEqual(20);
  });

  it("free tier has no monthly / annual price", () => {
    const free = getTier("free");
    expect(free.monthlyPriceUsd).toBe(0);
    expect(free.annualPriceUsd).toBe(0);
  });

  it("frontier tier is contact-sales (no public price)", () => {
    const frontier = getTier("frontier");
    expect(frontier.contactSales).toBe(true);
    expect(frontier.monthlyPriceUsd).toBeNull();
  });
});
