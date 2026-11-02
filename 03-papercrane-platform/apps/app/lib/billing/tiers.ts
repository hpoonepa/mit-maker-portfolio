/**
 * Paper Crane tier feature matrix: UI-facing.
 *
 * This is the copy the dashboard renders in the upgrade modal and on the
 * `/settings/billing` page. It intentionally diverges in a few places from
 * `@papercrane/billing`'s `TierFlags` / `PriceConfig`:
 *
 *   - Billing package is numeric ("maxConcurrent: 2") and drives enforcement.
 *   - This file is human strings ("2 jobs", "Unlimited") and drives display.
 *
 * Keeping them separate avoids accidentally leaking enforcement numbers into
 * marketing copy: when we bump Pro's concurrent cap from 20 → 40 we update
 * the billing package; when we rename a feature row we update this file.
 *
 * Numbers come from docs/plans/05-billing-pricing.md §1 (Feature Matrix).
 */

export type TierId = "free" | "pro" | "frontier";

export const PRO_MONTHLY_PRICE_USD = 299;
export const PRO_ANNUAL_PRICE_USD = 2990;

export interface TierDefinition {
  id: TierId;
  name: string;
  description: string;
  /** USD. Null for contact-sales tiers. */
  monthlyPriceUsd: number | null;
  /** USD. Null for contact-sales tiers. */
  annualPriceUsd: number | null;
  /** "Contact sales" CTA if true; hides the Subscribe button. */
  contactSales: boolean;
}

export const TIERS: readonly TierDefinition[] = [
  {
    id: "free",
    name: "Free",
    description: "500 seeds per month, 7-day retention, and public benchmarks.",
    monthlyPriceUsd: 0,
    annualPriceUsd: 0,
    contactSales: false,
  },
  {
    id: "pro",
    name: "Pro",
    description:
      "50,000 seeds per month, 90-day retention, and 20 concurrent jobs.",
    monthlyPriceUsd: PRO_MONTHLY_PRICE_USD,
    annualPriceUsd: PRO_ANNUAL_PRICE_USD,
    contactSales: false,
  },
  {
    id: "frontier",
    name: "Frontier",
    description: "Closed weights, VPC deployment, and onboarding support.",
    monthlyPriceUsd: null,
    annualPriceUsd: null,
    contactSales: true,
  },
] as const;

export type FeatureKey =
  | "seedsPerMonth"
  | "retention"
  | "maxConcurrent"
  | "closedWeights"
  | "vpc"
  | "support"
  | "seatAddOns"
  | "audit";

export interface FeatureRow {
  key: FeatureKey;
  label: string;
  values: Record<TierId, string>;
}

/**
 * Ordered so the upgrade modal reads top-to-bottom in importance. If you
 * reorder, update any snapshot tests that assert indices.
 */
const FEATURE_ROWS: readonly FeatureRow[] = [
  {
    key: "seedsPerMonth",
    label: "Seeds / month included",
    values: {
      free: "500",
      pro: "50,000",
      frontier: "Custom",
    },
  },
  {
    key: "retention",
    label: "Output retention",
    values: {
      free: "7 days",
      pro: "90 days",
      frontier: "Custom",
    },
  },
  {
    key: "maxConcurrent",
    label: "Max concurrent jobs",
    values: {
      free: "2",
      pro: "20",
      frontier: "Unlimited",
    },
  },
  {
    key: "closedWeights",
    label: "Closed-weights models (Chai, AF3)",
    values: {
      free: "N/A",
      pro: "N/A",
      frontier: "Included",
    },
  },
  {
    key: "vpc",
    label: "VPC / BYOC",
    values: {
      free: "N/A",
      pro: "N/A",
      frontier: "Included",
    },
  },
  {
    key: "support",
    label: "Support",
    values: {
      free: "Community",
      pro: "Email, 2 business days",
      frontier: "Shared Slack, 24h",
    },
  },
  {
    key: "seatAddOns",
    label: "Seats",
    values: {
      free: "1",
      pro: "5 included, $49/seat/mo after",
      frontier: "Unlimited",
    },
  },
  {
    key: "audit",
    label: "Audit log + SSO",
    values: {
      free: "N/A",
      pro: "SSO",
      frontier: "SSO + SCIM + audit log",
    },
  },
];

export function getTier(id: TierId): TierDefinition {
  const tier = TIERS.find((t) => t.id === id);
  if (!tier) throw new Error(`unknown tier: ${id}`);
  return tier;
}

export function listFeatures(): readonly FeatureRow[] {
  return FEATURE_ROWS;
}

export function compareFeature(key: FeatureKey, tier: TierId): string {
  const row = FEATURE_ROWS.find((r) => r.key === key);
  if (!row) throw new Error(`unknown feature: ${key}`);
  return row.values[tier];
}

/**
 * Percent saved by paying annually vs 12 months of the monthly plan.
 * Rounded down so we don't oversell.
 */
export function annualSavingsPercent(): number {
  // Widen to number so TS doesn't narrow the literal-const to a single value
  // and complain that the `=== 0` guard is unreachable.
  const annual: number = PRO_ANNUAL_PRICE_USD;
  const monthly: number = PRO_MONTHLY_PRICE_USD;
  if (annual === 0 || monthly === 0) return 0;
  const monthlyTotal = monthly * 12;
  const saved = monthlyTotal - annual;
  return Math.floor((saved / monthlyTotal) * 100);
}
