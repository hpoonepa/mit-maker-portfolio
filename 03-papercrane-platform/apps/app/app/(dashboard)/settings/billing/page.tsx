import { redirect } from "next/navigation";
import { CurrentPlanCard } from "@/components/billing/CurrentPlanCard";
import { UpgradeCTA } from "@/components/billing/UpgradeCTA";
import { BillingHistory } from "@/components/billing/BillingHistory";
import { SeatManagementCard } from "@/components/billing/SeatManagementCard";
import { GpuSpendCard } from "@/components/billing/GpuSpendCard";
import { createServerTrpc } from "@/lib/trpc/server";
import { getSessionUser } from "@/lib/supabase/server";
import type { TierId } from "@/lib/billing/tiers";

/**
 * Settings → Billing (RSC).
 *
 * Server-side work
 * ----------------
 *   1. Verify the Supabase session (middleware also guards, but defense in
 *      depth).
 *   2. Prefetch the current Subscription mirror via the server tRPC caller
 *      so `CurrentPlanCard` doesn't flash a skeleton on first paint.
 *
 * Everything else (invoice pagination, modal interactions, seat math) is
 * client-side via the components below. The `?checkout=success` query
 * parameter is surfaced as a toast client-side in `SuccessBanner`.
 *
 * Stripe redirect chain (reference)
 * ---------------------------------
 *   UpgradeModal → redirectToCheckout() → POST /v1/billing/checkout
 *     → (302) https://checkout.stripe.com/c/pay/cs_...
 *     → user completes payment
 *     → Stripe POSTs invoice.paid + customer.subscription.created to
 *        POST /v1/billing/webhook (tier flipped in DB)
 *     → Stripe 302 → /settings/billing?checkout=success
 *     → This page renders; useSubscription refetches and shows Pro.
 */

export default async function BillingPage({
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
    // TODO(@papercrane/trpc): replace with trpc.orgs.members.query().length
    seatsUsed = 1;
  } catch {
    // Best-effort prefetch; the client hook will retry.
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

      {isSuccess && <SuccessBanner />}

      <CurrentPlanCard initialTier={initialTier} seatsUsed={seatsUsed} />

      <GpuSpendCard />

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

function SuccessBanner() {
  return (
    <div
      role="status"
      className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 font-sans text-[13px] text-emerald-800"
    >
      Thanks for subscribing. Your workspace has been upgraded. It may take a
      moment to reflect while we process Stripe&rsquo;s webhook.
    </div>
  );
}
