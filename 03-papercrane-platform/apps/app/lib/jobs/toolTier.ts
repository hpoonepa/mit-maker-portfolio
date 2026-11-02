import type { ToolTier } from "@papercrane/types";

const TIER_RANK: Record<ToolTier, number> = {
  free: 0,
  pro: 1,
  frontier: 2,
};

/**
 * Client-side catalog gating. A missing usage period is treated as the free
 * tier so new organizations can still choose free tools; the submit endpoint
 * remains the authority for every tier check.
 */
export function isToolTierAllowed(
  requiredTier: ToolTier,
  userTier?: ToolTier,
): boolean {
  return TIER_RANK[requiredTier] <= TIER_RANK[userTier ?? "free"];
}
