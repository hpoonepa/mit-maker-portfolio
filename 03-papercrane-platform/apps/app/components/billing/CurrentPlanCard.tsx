"use client";

import { useState } from "react";
import { CheckCircle2, ExternalLink, Loader2 } from "lucide-react";
import { openPortal, PortalError } from "@/lib/billing/portal";
import { useSubscription } from "@/lib/billing/useSubscription";
import { getTier, type TierId } from "@/lib/billing/tiers";

/**
 * Renders the current plan + a "Manage in Stripe" button that routes users
 * to the Stripe Customer Portal. Free-tier users see the Free card and do
 * NOT get the portal button (there is no Stripe customer yet).
 *
 * Props:
 *   - `initialData` is the RSC-prefetched subscription summary. The client
 *     hook re-hydrates with the same data key, so there's no loading flash.
 *
 * TODO(@papercrane/ui): replace the inline Card/Button once packages/ui
 *                       exports primitives.
 */

export interface CurrentPlanCardProps {
  /** Pre-rendered tier to avoid a loading flash when the RSC page hydrates. */
  initialTier?: TierId;
  /** Seats currently consumed (from org.members count). */
  seatsUsed?: number;
  /** Seats included in the plan. */
  seatsIncluded?: number;
}

export function CurrentPlanCard({
  initialTier,
  seatsUsed = 1,
  seatsIncluded,
}: CurrentPlanCardProps) {
  const { data, isLoading } = useSubscription();
  const [portalLoading, setPortalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveTier: TierId = data?.tier ?? initialTier ?? "free";
  const tierDef = getTier(effectiveTier);
  const renewsAt = data?.renewsAt
    ? new Date(data.renewsAt).toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : null;

  const onManage = async () => {
    setError(null);
    setPortalLoading(true);
    try {
      await openPortal({ returnPath: "/settings/billing" });
      // `openPortal` redirects away; if we return, it failed silently.
    } catch (err) {
      if (err instanceof PortalError) {
        setError(err.message);
      } else {
        setError("Could not open Stripe portal.");
      }
      setPortalLoading(false);
    }
  };

  const canOpenPortal = !!data?.stripeCustomerId;

  return (
    <section className="p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Current plan
          </p>
          <h2 className="mt-2 font-display text-[28px] text-ink tracking-[-0.01em]">
            {isLoading ? "…" : tierDef.name}
          </h2>
          <p className="mt-1 font-sans text-[14px] text-graphite max-w-md">
            {tierDef.description}
          </p>
        </div>

        {effectiveTier !== "free" && (
          <div className="text-right">
            <p className="font-sans text-[12px] text-graphite-soft">
              Status
            </p>
            <p className="mt-1 font-mono text-[13px] text-ink flex items-center gap-1.5 justify-end">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              {data?.status ?? "active"}
            </p>
          </div>
        )}
      </div>

      <dl className="mt-8 grid gap-6 md:grid-cols-3">
        <Stat label="Tier" value={tierDef.name} />
        <Stat
          label="Seats"
          value={
            seatsIncluded
              ? `${seatsUsed} / ${seatsIncluded}`
              : `${seatsUsed}`
          }
        />
        <Stat
          label="Next invoice"
          value={renewsAt ?? (effectiveTier === "free" ? "N/A" : "Pending")}
        />
      </dl>

      {canOpenPortal && (
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onManage}
            disabled={portalLoading}
            className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90 disabled:opacity-60"
          >
            {portalLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ExternalLink className="h-4 w-4" />
            )}
            Manage in Stripe
          </button>
          {error && (
            <span className="font-sans text-[12px] text-red-600">{error}</span>
          )}
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-sans text-[12px] text-graphite-soft">
        {label}
      </dt>
      <dd className="mt-1 font-display text-[22px] text-ink tracking-[-0.01em]">
        {value}
      </dd>
    </div>
  );
}
