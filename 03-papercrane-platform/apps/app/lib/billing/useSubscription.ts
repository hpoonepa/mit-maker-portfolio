"use client";

/**
 * React Query wrapper around `trpc.billing.currentSubscription`. Exists so
 * client components have a stable, opinionated signature that derives
 * UI-shaped fields (tier label, renewal date string, Free flag) from the
 * raw DB row: and so we can swap the data source later without rewriting
 * every caller.
 */

import { trpc } from "@/lib/trpc/client";
import type { TierId } from "./tiers";

export interface SubscriptionSummary {
  /** The effective UI tier. 'free' when there is no Subscription row. */
  tier: TierId;
  /** Human label: 'Free', 'Pro', 'Frontier'. */
  tierLabel: string;
  /** ISO string of the next billing period end, or null for Free. */
  renewsAt: string | null;
  /** Stripe customer id, or null if the org has never subscribed. */
  stripeCustomerId: string | null;
  /** 'active' | 'trialing' | 'past_due' | ... | null when Free. */
  status: string | null;
  /** Convenience flag for gating surfaces. */
  isFree: boolean;
  /** Convenience flag. */
  isPro: boolean;
  /** Convenience flag. */
  isFrontier: boolean;
}

export interface UseSubscriptionResult {
  data: SubscriptionSummary | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
}

const TIER_LABEL: Record<TierId, string> = {
  free: "Free",
  pro: "Pro",
  frontier: "Frontier",
};

export function useSubscription(): UseSubscriptionResult {
  const query = trpc.billing.currentSubscription.useQuery(undefined, {
    // Subscriptions change rarely; webhooks invalidate. Stale-while-revalidate
    // in the background on focus.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  const raw = query.data ?? null;
  const summary: SubscriptionSummary | undefined = query.isLoading
    ? undefined
    : deriveSummary(raw);

  return {
    data: summary,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: () => query.refetch(),
  };
}

function deriveSummary(
  raw: {
    tier: string;
    status: string;
    currentPeriodEnd: Date | string;
    stripeCustomerId: string | null;
  } | null,
): SubscriptionSummary {
  if (!raw) {
    return {
      tier: "free",
      tierLabel: TIER_LABEL.free,
      renewsAt: null,
      stripeCustomerId: null,
      status: null,
      isFree: true,
      isPro: false,
      isFrontier: false,
    };
  }
  const tier = (raw.tier as TierId) ?? "free";
  const renewsAt =
    raw.currentPeriodEnd instanceof Date
      ? raw.currentPeriodEnd.toISOString()
      : String(raw.currentPeriodEnd);
  return {
    tier,
    tierLabel: TIER_LABEL[tier] ?? tier,
    renewsAt,
    stripeCustomerId: raw.stripeCustomerId,
    status: raw.status,
    isFree: tier === "free",
    isPro: tier === "pro",
    isFrontier: tier === "frontier",
  };
}
