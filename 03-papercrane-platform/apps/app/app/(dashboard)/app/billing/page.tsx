import { redirect } from "next/navigation";
import { CurrentPlanCard } from "@/components/billing/CurrentPlanCard";
import { UpgradeCTA } from "@/components/billing/UpgradeCTA";
import { BillingHistory } from "@/components/billing/BillingHistory";
import { SeatManagementCard } from "@/components/billing/SeatManagementCard";
import { createServerTrpc } from "@/lib/trpc/server";
import { getSessionUser } from "@/lib/supabase/server";
import type { TierId } from "@/lib/billing/tiers";

/**
 * `/app/billing`: billing landing surfaced inside the workspace nav.
 *
 * Mirrors the canonical `/settings/billing` page so we can keep a single
 * source of truth for plan + invoice components while still giving users
 * an in-workspace shortcut. Server-renders the prefetched tier so the
 * upgrade CTA doesn't flash.
 */
export default async function BillingPage({
  searchParams,
}: {
  searchParams?: Promise<{ checkout?: string; success?: string }>;
}) {
  const user = await getSessionUser();
  if (!user) redirect("/login?next=/app/billing");

  const params = (await searchParams) ?? {};
  const isSuccess = params.checkout === "success" || params.success === "true";

  let initialTier: TierId = "free";
  let seatsUsed = 1;
  try {
    const trpc = await createServerTrpc();
    const sub = await trpc.billing.currentSubscription.query();
    if (sub && typeof sub.tier === "string") {
      initialTier = (sub.tier as TierId) ?? "free";
    }
    seatsUsed = 1;
  } catch {
    // Best-effort prefetch; client hooks handle retries.
  }

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">
          Plan &amp; usage
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          Track your seat usage, manage your subscription, and review past
          invoices.
        </p>
      </header>

      {isSuccess && (
        <div
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 font-sans text-[13px] text-emerald-800"
        >
          Thanks for subscribing. Your workspace has been upgraded. It may
          take a moment to reflect while we process Stripe&rsquo;s webhook.
        </div>
      )}

      <CurrentPlanCard initialTier={initialTier} seatsUsed={seatsUsed} />

      {initialTier === "free" && (
        <UpgradeCTA variant="card" label="Upgrade to Pro" />
      )}

      {initialTier !== "free" && (
        <SeatManagementCard currentSeats={seatsUsed} />
      )}

      <BillingHistory />
    </div>
  );
}
