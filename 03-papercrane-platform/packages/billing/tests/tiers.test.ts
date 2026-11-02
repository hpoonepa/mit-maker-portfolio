import { describe, expect, it } from "vitest";
import {
  resolvePriceConfig,
  proTierFlags,
  freeTierFlags,
  type BillingPriceEnv,
} from "../src/tiers.js";

/**
 * Price → tier mapping.
 *
 * The billing package only knows about two "real" tiers for self-serve:
 *   - Free (default, no Stripe subscription)
 *   - Pro (monthly or annual price IDs, same tier config)
 *
 * The seat add-on and seed pack price IDs are acknowledged but do NOT change
 * the org's tier — they are side purchases handled outside subscription-tier
 * sync. We only assert that the mapper does not mis-classify them as tier
 * changes.
 *
 * Frontier is out-of-band (manual Invoice flow, not Stripe Subscription).
 */

const env: BillingPriceEnv = {
  STRIPE_PRICE_PRO_MONTHLY: "price_pro_monthly_test",
  STRIPE_PRICE_PRO_ANNUAL: "price_pro_annual_test",
  STRIPE_PRICE_SEAT_ADDON: "price_seat_addon_test",
  STRIPE_PRICE_PACK_10K: "price_pack_10k_test",
};

describe("resolvePriceConfig", () => {
  it("maps Pro monthly price to the Pro tier config", () => {
    const cfg = resolvePriceConfig("price_pro_monthly_test", env);
    expect(cfg).not.toBeNull();
    expect(cfg!.tier).toBe("pro");
    expect(cfg!.seedsQuota).toBe(50_000);
    expect(cfg!.flags.retentionDays).toBe(90);
    expect(cfg!.flags.maxConcurrent).toBe(20);
    expect(cfg!.flags.closedWeightsAllowed).toBe(false);
  });

  it("maps Pro annual price to the Pro tier config (same as monthly)", () => {
    const cfg = resolvePriceConfig("price_pro_annual_test", env);
    expect(cfg).not.toBeNull();
    expect(cfg!.tier).toBe("pro");
    expect(cfg!.seedsQuota).toBe(50_000);
  });

  it("returns null for the seat add-on — not a tier change", () => {
    expect(resolvePriceConfig("price_seat_addon_test", env)).toBeNull();
  });

  it("returns null for a seed pack — not a tier change", () => {
    expect(resolvePriceConfig("price_pack_10k_test", env)).toBeNull();
  });

  it("returns null for an unknown price id", () => {
    expect(resolvePriceConfig("price_garbage", env)).toBeNull();
  });
});

describe("tier flag deltas", () => {
  it("freeTierFlags matches the Free defaults in the schema", () => {
    expect(freeTierFlags).toEqual({
      retentionDays: 7,
      maxConcurrent: 2,
      closedWeightsAllowed: false,
      vpcEnabled: false,
      byocRequired: false,
    });
  });

  it("proTierFlags raises retention and concurrency but keeps closed weights off", () => {
    expect(proTierFlags.retentionDays).toBe(90);
    expect(proTierFlags.maxConcurrent).toBe(20);
    expect(proTierFlags.closedWeightsAllowed).toBe(false);
    expect(proTierFlags.vpcEnabled).toBe(false);
  });
});
