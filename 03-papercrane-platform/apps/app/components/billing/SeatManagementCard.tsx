"use client";

import { useState } from "react";
import { Loader2, Minus, Plus, Users } from "lucide-react";
import { CheckoutError, redirectToCheckout } from "@/lib/billing/checkout";
import { openPortal, PortalError } from "@/lib/billing/portal";
import { useSubscription } from "@/lib/billing/useSubscription";

/**
 * Seat management card.
 *
 * Purchase path
 * -------------
 * Adding seats is a metered subscription-item update: the Stripe Customer
 * Portal already handles this cleanly (add/remove/cancel items + proration),
 * so we route the user there instead of re-implementing it.
 *
 * First purchase
 * --------------
 * If the org doesn't have a Pro subscription yet, adding seats doesn't make
 * sense: we hide the card. Once they subscribe, the SEAT add-on price id
 * (NEXT_PUBLIC_STRIPE_PRICE_SEAT_ADDON) can optionally drive a "Buy seats"
 * direct checkout for orgs that prefer a one-click flow.
 *
 * TODO: wire to a future `billing.seats.useMutation` once we add inline seat
 * CRUD to the API. For now, portal-first.
 */

export interface SeatManagementCardProps {
  /** Total seats currently assigned to this org. */
  currentSeats: number;
  /** Seats included in the base Pro plan (default: 5). */
  includedSeats?: number;
  /** Monthly USD per extra seat. */
  perSeatMonthlyUsd?: number;
  /** Stripe price id for the seat add-on; defaults to env. */
  seatAddonPriceId?: string;
}

export function SeatManagementCard({
  currentSeats,
  includedSeats = 5,
  perSeatMonthlyUsd = 49,
  seatAddonPriceId = process.env.NEXT_PUBLIC_STRIPE_PRICE_SEAT_ADDON,
}: SeatManagementCardProps) {
  const { data } = useSubscription();
  const [targetSeats, setTargetSeats] = useState(currentSeats);
  const [busy, setBusy] = useState<"buy" | "portal" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Don't show on Free: no subscription to attach seats to.
  if (!data || data.isFree) return null;

  const extraSeats = Math.max(0, targetSeats - includedSeats);
  const monthlyAddOn = extraSeats * perSeatMonthlyUsd;

  const inc = () => setTargetSeats((n) => n + 1);
  const dec = () => setTargetSeats((n) => Math.max(1, n - 1));

  const onBuySeats = async () => {
    if (!seatAddonPriceId) {
      setError("NEXT_PUBLIC_STRIPE_PRICE_SEAT_ADDON is not configured.");
      return;
    }
    setError(null);
    setBusy("buy");
    try {
      await redirectToCheckout({
        priceId: seatAddonPriceId,
        returnPath: "/settings/billing",
      });
    } catch (err) {
      setBusy(null);
      if (err instanceof CheckoutError) setError(err.message);
      else setError("Could not start seat checkout.");
    }
  };

  const onManageInPortal = async () => {
    setError(null);
    setBusy("portal");
    try {
      await openPortal({ returnPath: "/settings/billing" });
    } catch (err) {
      setBusy(null);
      if (err instanceof PortalError) setError(err.message);
      else setError("Could not open Stripe portal.");
    }
  };

  return (
    <section className="p-8">
      <header className="flex items-center gap-3">
        <Users className="h-5 w-5 text-ink" />
        <h2 className="font-display text-[22px] text-ink tracking-[-0.01em]">
          Seats
        </h2>
      </header>

      <p className="mt-2 font-sans text-[14px] text-graphite max-w-md">
        Pro includes {includedSeats} seats. Additional seats are $
        {perSeatMonthlyUsd}/seat/month, prorated.
      </p>

      <div className="mt-6 flex items-center gap-4">
        <button
          type="button"
          onClick={dec}
          disabled={targetSeats <= 1}
          className="rounded-full border border-lattice p-2 disabled:opacity-50"
        >
          <Minus className="h-4 w-4" />
        </button>
        <div className="w-16 text-center">
          <p className="font-display text-[32px] text-ink tracking-[-0.02em]">
            {targetSeats}
          </p>
          <p className="font-sans text-[12px] text-graphite-soft">
            Seats
          </p>
        </div>
        <button
          type="button"
          onClick={inc}
          className="rounded-full border border-lattice p-2"
        >
          <Plus className="h-4 w-4" />
        </button>

        <div className="ml-auto text-right">
          <p className="font-sans text-[12px] text-graphite-soft">
            Extra / month
          </p>
          <p className="mt-1 font-display text-[22px] text-ink tracking-[-0.01em]">
            ${monthlyAddOn.toLocaleString()}
          </p>
        </div>
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onBuySeats}
          disabled={extraSeats === 0 || busy !== null || !seatAddonPriceId}
          className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90 disabled:opacity-60"
        >
          {busy === "buy" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          {extraSeats === 0
            ? "Add seats above included"
            : `Buy ${extraSeats} seat${extraSeats === 1 ? "" : "s"}`}
        </button>

        <button
          type="button"
          onClick={onManageInPortal}
          disabled={busy !== null}
          className="rounded-full border border-lattice px-4 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold/50 disabled:opacity-60"
        >
          {busy === "portal" ? "Opening…" : "Manage in Stripe"}
        </button>

        {error && (
          <span className="font-sans text-[12px] text-red-600">{error}</span>
        )}
      </div>
    </section>
  );
}
