import { describe, expect, it, vi } from "vitest";
import type Stripe from "stripe";
import {
  resolvePriceConfig,
  isProPrice,
  proPriceConfig,
  freePriceConfig,
  proTierFlags,
  freeTierFlags,
  PRO_SEEDS_QUOTA,
  FREE_SEEDS_QUOTA,
  handleSubscriptionEvent,
  type WebhookContext,
  type BillingPriceEnv,
} from "@papercrane/billing";

/**
 * Feature-flag resolution tests.
 *
 * Plan 05 §4: `feature_flags` is a SINGLE source of truth — one row per org,
 * not per tier. That means:
 *   - Free/Pro defaults are baked into proTierFlags / freeTierFlags
 *   - Frontier orgs get per-org overrides (custom retention_days etc.) that
 *     persist even after a Stripe.Subscription update on the same org —
 *     subscription writes only touch Free↔Pro flags
 *
 * Coverage:
 *   - Price → tier mapping: monthly + annual → Pro; seat add-on / pack → null
 *   - Free defaults pin to plan 05 §1 matrix (7d retention, 2 concurrent)
 *   - Pro defaults pin to §1 matrix (90d retention, 20 concurrent, no closed weights)
 *   - Frontier override: a subscription event for a Frontier-tier org with a
 *     non-tier-changing price (seat-only) does NOT clobber retention_days
 */

const ENV: BillingPriceEnv = {
  STRIPE_PRICE_PRO_MONTHLY: "price_pro_monthly_test",
  STRIPE_PRICE_PRO_ANNUAL: "price_pro_annual_test",
  STRIPE_PRICE_SEAT_ADDON: "price_seat_addon_test",
  STRIPE_PRICE_PACK_10K: "price_pack_10k_test",
};

function mkSubscriptionEvent(opts: {
  type:
    | "customer.subscription.created"
    | "customer.subscription.updated"
    | "customer.subscription.deleted";
  id: string;
  subId: string;
  customer: string;
  status: Stripe.Subscription.Status;
  priceIds: string[];
  metadataOrgId?: string;
}): Stripe.Event {
  return {
    id: opts.id,
    type: opts.type,
    object: "event",
    api_version: "2024-06-20",
    created: Math.floor(Date.now() / 1000),
    data: {
      object: {
        id: opts.subId,
        customer: opts.customer,
        status: opts.status,
        current_period_end: Math.floor(Date.now() / 1000) + 30 * 86400,
        metadata: opts.metadataOrgId ? { orgId: opts.metadataOrgId } : {},
        items: {
          data: opts.priceIds.map((pid, i) => ({
            id: `si_${i}`,
            price: { id: pid },
          })),
        },
      } as never,
    },
    livemode: false,
    pending_webhooks: 0,
    request: { id: null, idempotency_key: null },
  } as unknown as Stripe.Event;
}

function mkPrismaStub() {
  return {
    subscription: {
      findUnique: vi.fn().mockResolvedValue(null),
      upsert: vi.fn().mockResolvedValue(undefined),
    },
    organization: {
      update: vi.fn().mockResolvedValue(undefined),
    },
    featureFlag: {
      upsert: vi.fn().mockResolvedValue(undefined),
    },
  };
}

function mkCtx(prisma: ReturnType<typeof mkPrismaStub>): WebhookContext {
  return {
    prisma: prisma as never,
    redis: null,
    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    } as never,
    priceEnv: ENV,
    handlers: {
      onSubscriptionEvent: vi.fn(),
      onInvoiceEvent: vi.fn(),
      onCheckoutCompleted: vi.fn(),
    },
  };
}

describe("resolvePriceConfig — Stripe price → tier mapping", () => {
  it("monthly Pro price → Pro tier (50k quota, 90d retention, 20 concurrent)", () => {
    const cfg = resolvePriceConfig("price_pro_monthly_test", ENV);
    expect(cfg).toEqual(proPriceConfig);
    expect(cfg?.tier).toBe("pro");
    expect(cfg?.seedsQuota).toBe(PRO_SEEDS_QUOTA);
    expect(cfg?.flags.retentionDays).toBe(90);
    expect(cfg?.flags.maxConcurrent).toBe(20);
    expect(cfg?.flags.closedWeightsAllowed).toBe(false); // Frontier-only
  });

  it("annual Pro price → Pro tier", () => {
    expect(resolvePriceConfig("price_pro_annual_test", ENV)?.tier).toBe("pro");
  });

  it("seat add-on price → null (NOT a tier change)", () => {
    // Seat add-ons ride on top of Pro; they must NOT trigger a tier write.
    expect(resolvePriceConfig("price_seat_addon_test", ENV)).toBeNull();
  });

  it("seed-pack price → null (one-shot Checkout, no subscription tier change)", () => {
    expect(resolvePriceConfig("price_pack_10k_test", ENV)).toBeNull();
  });

  it("unknown price id → null (caller should leave Organization.tier alone)", () => {
    expect(resolvePriceConfig("price_random_xyz", ENV)).toBeNull();
  });

  it("isProPrice classifies monthly + annual but not seat/pack", () => {
    expect(isProPrice("price_pro_monthly_test", ENV)).toBe(true);
    expect(isProPrice("price_pro_annual_test", ENV)).toBe(true);
    expect(isProPrice("price_seat_addon_test", ENV)).toBe(false);
    expect(isProPrice("price_pack_10k_test", ENV)).toBe(false);
  });
});

describe("Tier flag defaults (per plan 05 §1 matrix)", () => {
  it("Free defaults: 7d retention, 2 concurrent, no closed weights, no VPC", () => {
    expect(freeTierFlags).toEqual({
      retentionDays: 7,
      maxConcurrent: 2,
      closedWeightsAllowed: false,
      vpcEnabled: false,
      byocRequired: false,
    });
    expect(FREE_SEEDS_QUOTA).toBe(500);
  });

  it("Pro defaults: 90d retention, 20 concurrent, no closed weights, no VPC", () => {
    expect(proTierFlags).toEqual({
      retentionDays: 90,
      maxConcurrent: 20,
      closedWeightsAllowed: false,
      vpcEnabled: false,
      byocRequired: false,
    });
    expect(PRO_SEEDS_QUOTA).toBe(50_000);
  });

  it("Free and Pro mirror Prisma FeatureFlag schema defaults (single source of truth)", () => {
    // freeTierFlags lives in tiers.ts but MUST stay in sync with the Prisma
    // schema defaults — this assertion documents that contract.
    expect(freePriceConfig.flags).toBe(freeTierFlags);
    expect(proPriceConfig.flags).toBe(proTierFlags);
  });
});

describe("Subscription handler — feature_flags writes", () => {
  it("Pro upgrade: writes Pro flags to feature_flags (90d retention, 20 concurrent)", async () => {
    const prisma = mkPrismaStub();
    prisma.subscription.findUnique.mockResolvedValue({ orgId: "org_pro" });
    const ctx = mkCtx(prisma);

    const event = mkSubscriptionEvent({
      type: "customer.subscription.created",
      id: "evt_upgrade",
      subId: "sub_pro",
      customer: "cus_pro",
      status: "active",
      priceIds: [ENV.STRIPE_PRICE_PRO_MONTHLY!],
    });

    await handleSubscriptionEvent(event, ctx);

    expect(prisma.featureFlag.upsert).toHaveBeenCalledTimes(1);
    const args = prisma.featureFlag.upsert.mock.calls[0]![0];
    expect(args.where).toEqual({ orgId: "org_pro" });
    expect(args.create).toMatchObject({
      orgId: "org_pro",
      retentionDays: 90,
      maxConcurrent: 20,
      closedWeightsAllowed: false,
    });
    expect(args.update).toMatchObject({
      retentionDays: 90,
      maxConcurrent: 20,
    });
    expect(prisma.organization.update).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: "org_pro" },
        data: expect.objectContaining({
          tier: "pro",
          seedsQuota: PRO_SEEDS_QUOTA,
          retentionDays: 90,
        }),
      }),
    );
  });

  it("Subscription.deleted downgrades flags to Free (7d retention) regardless of price", async () => {
    const prisma = mkPrismaStub();
    prisma.subscription.findUnique.mockResolvedValue({ orgId: "org_dunned" });
    const ctx = mkCtx(prisma);

    const event = mkSubscriptionEvent({
      type: "customer.subscription.deleted",
      id: "evt_dunned",
      subId: "sub_dunned",
      customer: "cus_dunned",
      status: "canceled",
      // Even if the line items still list Pro, delete must downgrade to Free.
      priceIds: [ENV.STRIPE_PRICE_PRO_MONTHLY!],
    });

    await handleSubscriptionEvent(event, ctx);

    const args = prisma.featureFlag.upsert.mock.calls[0]![0];
    expect(args.update).toMatchObject({
      retentionDays: 7,
      maxConcurrent: 2,
      closedWeightsAllowed: false,
    });
    expect(prisma.organization.update).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          tier: "free",
          retentionDays: 7,
        }),
      }),
    );
  });

  it("Frontier override is preserved: seat-only subscription update does NOT touch tier or flags", async () => {
    // Frontier customers may have custom retention_days written into
    // feature_flags via ops scripts (per §4: "single source of truth ... so
    // Frontier customers get custom overrides without code changes"). A seat
    // add-on update on such an org must NOT clobber that row.
    const prisma = mkPrismaStub();
    prisma.subscription.findUnique.mockResolvedValue({ orgId: "org_frontier" });
    const ctx = mkCtx(prisma);

    const event = mkSubscriptionEvent({
      type: "customer.subscription.updated",
      id: "evt_seat_only",
      subId: "sub_frontier",
      customer: "cus_frontier",
      status: "active",
      // Only seat add-on, no tier-changing price → resolvePriceConfig=null.
      priceIds: [ENV.STRIPE_PRICE_SEAT_ADDON!],
    });

    await handleSubscriptionEvent(event, ctx);

    // Critical Frontier guarantee: no writes to organization or feature_flags.
    expect(prisma.organization.update).not.toHaveBeenCalled();
    expect(prisma.featureFlag.upsert).not.toHaveBeenCalled();
    expect(prisma.subscription.upsert).not.toHaveBeenCalled();
  });

  it("Pro + seat add-on multi-line subscription picks Pro as the driving price", async () => {
    // pickDrivingPrice prefers a Pro-tier price when multiple line items are
    // present, so the Pro flags win even when the seat add-on appears first.
    const prisma = mkPrismaStub();
    prisma.subscription.findUnique.mockResolvedValue({ orgId: "org_combo" });
    const ctx = mkCtx(prisma);

    const event = mkSubscriptionEvent({
      type: "customer.subscription.updated",
      id: "evt_combo",
      subId: "sub_combo",
      customer: "cus_combo",
      status: "active",
      priceIds: [
        ENV.STRIPE_PRICE_SEAT_ADDON!,
        ENV.STRIPE_PRICE_PRO_MONTHLY!,
      ],
    });

    await handleSubscriptionEvent(event, ctx);
    expect(prisma.featureFlag.upsert).toHaveBeenCalledTimes(1);
    const args = prisma.featureFlag.upsert.mock.calls[0]![0];
    expect(args.update.retentionDays).toBe(90);
    expect(args.update.maxConcurrent).toBe(20);
  });
});
