import { redirect } from "next/navigation";
import { CurrentPlanCard } from "@/components/billing/CurrentPlanCard";
import { UpgradeCTA } from "@/components/billing/UpgradeCTA";
import { BillingHistory } from "@/components/billing/BillingHistory";
import { SeatManagementCard } from "@/components/billing/SeatManagementCard";
import { createServerTrpc } from "@/lib/trpc/server";
import { getSessionUser } from "@/lib/supabase/server";
import type { TierId } from "@/lib/billing/tiers";

/**
 * `/app/settings/billing`: plan, seats, and invoices, rendered as a
 * nested settings tab.
 *
 * Functionally identical to `/settings/billing` but lives under the
 * `/app/settings/*` umbrella so both URLs work while the dashboard
 * migration finishes. We re-use the same billing components and the
 * same server-side prefetch pattern so the two routes never drift.
 *
 * Stripe redirect chain (reference)
 * ---------------------------------
 *   UpgradeModal → POST /v1/billing/checkout (302 to Stripe)
 *     → user pays → Stripe → webhook flips tier in DB
 *     → 302 → /app/settings/billing?checkout=success
 *     → SuccessBanner toasts, useSubscription refetches.
 */
export default async function BillingSettingsPage({
  searchParams,
}: {
  searchParams?: Promise<{ checkout?: string; success?: string }>;
}) {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const params = (await searchParams) ?? {};
  const isSuccess =
    params.checkout === "success" || params.success === "true";

  let initialTier: TierId = "free";
  let seatsUsed = 1;
  try {
    const trpc = await createServerTrpc();
    const sub = await trpc.billing.currentSubscription.query();
    if (sub && typeof sub.tier === "string") {
      initialTier = (sub.tier as TierId) ?? "free";
    }
    try {
      const members = await trpc.members.list.query();
      seatsUsed = Math.max(1, members.items?.length ?? 1);
    } catch {
      // best-effort: seat count isn't critical for first paint
    }
  } catch {
    // best-effort prefetch; the client hook will retry
  }

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">
          Plan &amp; invoices
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          Manage your Paper Crane subscription, seats, and invoices.
        </p>
      </header>

      {isSuccess ? <SuccessBanner /> : null}

      <CurrentPlanCard initialTier={initialTier} seatsUsed={seatsUsed} />

      {initialTier === "free" ? (
        <UpgradeCTA variant="card" label="Upgrade to Pro" />
      ) : (
        <SeatManagementCard currentSeats={seatsUsed} />
      )}

      <BillingHistory />
    </div>
  );
}

function SuccessBanner() {
  return (
    <div
      role="status"
      className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 font-sans text-[13px] text-emerald-800"
    >
      Thanks for subscribing. Your workspace has been upgraded. It may take
      a moment to reflect while we process Stripe&rsquo;s webhook.
    </div>
  );
}
