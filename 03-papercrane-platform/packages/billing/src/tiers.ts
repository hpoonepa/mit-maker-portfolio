/**
 * Price → tier / feature-flag mapping.
 *
 * The Free defaults in the Prisma schema (`FeatureFlag`) are the source of
 * truth for downgrades; we mirror them here so the billing package can run
 * without reaching into the DB migration. If the schema changes, update
 * `freeTierFlags` below in the same PR.
 *
 * Pro config comes from docs/plans/05-billing-pricing.md §1 (Feature Matrix)
 * and §4 (Tier Enforcement Gateway):
 *
 *   seeds/month included   50,000
 *   retention              90 days
 *   max concurrent jobs    20
 *   closed weights         No (that's Frontier-only)
 *
 * Seat add-ons and seed packs are explicitly NOT tier changes. They are
 * priced as extra subscription items / one-shot Checkout sessions handled by
 * their own flows; when the webhook dispatcher sees one it should not touch
 * the org's tier. `resolvePriceConfig` returns `null` for those so callers
 * can short-circuit cleanly.
 */

export type OrgTier = "free" | "pro" | "frontier";

export interface TierFlags {
  retentionDays: number;
  maxConcurrent: number;
  closedWeightsAllowed: boolean;
  vpcEnabled: boolean;
  byocRequired: boolean;
}

export interface PriceConfig {
  tier: OrgTier;
  seedsQuota: number;
  flags: TierFlags;
}

/**
 * Env vars are passed in explicitly rather than read via `process.env`. This
 * keeps the mapper pure (trivial to test) and lets the caller swap config per
 * environment without re-importing.
 */
export interface BillingPriceEnv {
  STRIPE_PRICE_PRO_MONTHLY?: string;
  STRIPE_PRICE_PRO_ANNUAL?: string;
  STRIPE_PRICE_SEAT_ADDON?: string;
  STRIPE_PRICE_PACK_10K?: string;
}

// Feature-flag defaults mirror packages/db/prisma/schema.prisma (FeatureFlag).
export const freeTierFlags: TierFlags = {
  retentionDays: 7,
  maxConcurrent: 2,
  closedWeightsAllowed: false,
  vpcEnabled: false,
  byocRequired: false,
};

export const proTierFlags: TierFlags = {
  retentionDays: 90,
  maxConcurrent: 20,
  closedWeightsAllowed: false,
  vpcEnabled: false,
  byocRequired: false,
};

export const PRO_SEEDS_QUOTA = 50_000;
export const FREE_SEEDS_QUOTA = 500;

export const proPriceConfig: PriceConfig = {
  tier: "pro",
  seedsQuota: PRO_SEEDS_QUOTA,
  flags: proTierFlags,
};

export const freePriceConfig: PriceConfig = {
  tier: "free",
  seedsQuota: FREE_SEEDS_QUOTA,
  flags: freeTierFlags,
};

/**
 * Return the tier config for a Stripe price id, or null if the price id is
 * not a tier-changing price (seat add-on, seed pack, unknown).
 *
 * Callers should treat `null` as "don't touch Organization.tier" — it does
 * NOT mean "unknown price, error out". Add-ons and packs go through their
 * own side flows.
 */
export function resolvePriceConfig(
  priceId: string,
  env: BillingPriceEnv,
): PriceConfig | null {
  if (
    priceId === env.STRIPE_PRICE_PRO_MONTHLY ||
    priceId === env.STRIPE_PRICE_PRO_ANNUAL
  ) {
    return proPriceConfig;
  }
  // Seat + pack are explicit non-tier prices.
  if (priceId === env.STRIPE_PRICE_SEAT_ADDON) return null;
  if (priceId === env.STRIPE_PRICE_PACK_10K) return null;
  return null;
}

/**
 * Cheap classifier — does this price represent a Pro subscription? Used by
 * the subscription handler when the incoming Stripe.Subscription has multiple
 * line items (Pro plan + seat add-on) and we need to pick which one drives
 * the tier.
 */
export function isProPrice(priceId: string, env: BillingPriceEnv): boolean {
  return (
    priceId === env.STRIPE_PRICE_PRO_MONTHLY ||
    priceId === env.STRIPE_PRICE_PRO_ANNUAL
  );
}
