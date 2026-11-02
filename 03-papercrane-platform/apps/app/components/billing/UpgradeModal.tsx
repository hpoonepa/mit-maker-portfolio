"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import {
  PRO_ANNUAL_PRICE_USD,
  PRO_MONTHLY_PRICE_USD,
  annualSavingsPercent,
  getTier,
  listFeatures,
  type FeatureRow,
  type TierId,
} from "@/lib/billing/tiers";
import { CheckoutError, redirectToCheckout } from "@/lib/billing/checkout";

/**
 * Upgrade modal: shows the Free/Pro comparison, lets the user pick a
 * billing cadence, and kicks off Stripe Checkout. The component is
 * controlled (`open` + `onClose`) so multiple triggers (sidebar button,
 * gate-modal shim) can share it.
 *
 * Price IDs come from env via NEXT_PUBLIC_* so the Checkout URL redirect
 * chain is deterministic per deploy. Missing env → disabled button with a
 * helpful hint.
 *
 * TODO(@papercrane/ui): swap the raw <dialog> for the Modal primitive once
 *                       `packages/ui/Modal` lands.
 */

export interface UpgradeModalProps {
  open: boolean;
  onClose: () => void;
  /** Which tier to highlight; defaults to Pro. */
  highlightTier?: TierId;
  /** Override env: testing only. */
  monthlyPriceId?: string;
  annualPriceId?: string;
}

type Cadence = "monthly" | "annual";

export function UpgradeModal({
  open,
  onClose,
  highlightTier = "pro",
  monthlyPriceId = process.env.NEXT_PUBLIC_STRIPE_PRICE_PRO_MONTHLY,
  annualPriceId = process.env.NEXT_PUBLIC_STRIPE_PRICE_PRO_ANNUAL,
}: UpgradeModalProps) {
  const [cadence, setCadence] = useState<Cadence>("annual");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  // Escape-to-close: tiny bit of a11y until the UI package ships a Modal.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const pro = getTier("pro");
  const priceUsd =
    cadence === "monthly" ? PRO_MONTHLY_PRICE_USD : PRO_ANNUAL_PRICE_USD;
  const cadenceLabel = cadence === "monthly" ? "per month" : "per year";
  const savings = annualSavingsPercent();
  const activePriceId = cadence === "monthly" ? monthlyPriceId : annualPriceId;
  const missingPrice = !activePriceId;

  const onSubscribe = async () => {
    if (!activePriceId) {
      setError("Stripe price id is not configured.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await redirectToCheckout({
        priceId: activePriceId,
        returnPath: "/settings/billing",
      });
      // If we return here, the navigate didn't happen: no-op.
    } catch (err) {
      setSubmitting(false);
      if (err instanceof CheckoutError) {
        setError(err.message);
      } else {
        setError("Could not start checkout. Please try again.");
      }
    }
  };

  const features = listFeatures();

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="upgrade-title"
      data-testid="e2e-upgrade-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl bg-paper p-8 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="absolute right-5 top-5 rounded-full p-1.5 text-graphite hover:bg-lattice/50"
        >
          <X className="h-4 w-4" />
        </button>

        <header>
          <p className="font-sans text-[12px] text-graphite-soft">
            Upgrade
          </p>
          <h2
            id="upgrade-title"
            className="mt-2 font-display text-display-md text-ink"
          >
            {pro.name}
          </h2>
          <p className="mt-2 font-sans text-[14px] text-graphite max-w-md">
            {pro.description}
          </p>
        </header>

        {/* Cadence toggle */}
        <div
          role="radiogroup"
          aria-label="Billing cadence"
          className="mt-6 inline-flex items-center gap-1 rounded-full p-1"
        >
          <CadenceButton
            active={cadence === "monthly"}
            onClick={() => setCadence("monthly")}
            label="Monthly"
          />
          <CadenceButton
            active={cadence === "annual"}
            onClick={() => setCadence("annual")}
            label={`Annual (save ${savings}%)`}
          />
        </div>

        <div className="mt-6 flex items-baseline gap-2">
          <span className="font-display text-[40px] text-ink tracking-[-0.02em]">
            ${priceUsd.toLocaleString()}
          </span>
          <span className="font-sans text-[13px] text-graphite">
            {cadenceLabel}
          </span>
        </div>

        <FeatureList features={features} highlight={highlightTier} />

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onSubscribe}
            disabled={submitting || missingPrice}
            data-testid="e2e-upgrade-subscribe"
            className="inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 font-sans text-[14px] text-paper hover:bg-ink/90 disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Subscribe
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-lattice px-5 py-2.5 font-sans text-[13px] text-ink hover:bg-paper-fold/50"
          >
            Not now
          </button>
          {missingPrice && (
            <span className="font-sans text-[12px] text-amber-600">
              NEXT_PUBLIC_STRIPE_PRICE_PRO_{cadence.toUpperCase()} is not set.
            </span>
          )}
          {error && (
            <span className="font-sans text-[12px] text-red-600">{error}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function CadenceButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={
        "rounded-full px-4 py-1.5 font-sans text-[12px] transition " +
        (active
          ? "bg-ink text-paper"
          : "text-graphite hover:text-ink")
      }
    >
      {label}
    </button>
  );
}

function FeatureList({
  features,
  highlight,
}: {
  features: readonly FeatureRow[];
  highlight: TierId;
}) {
  return (
    <ul className="mt-7 space-y-2">
      {features.map((row) => (
        <li
          key={row.key}
          className="flex items-center justify-between pb-2"
        >
          <span className="font-sans text-[13px] text-ink">{row.label}</span>
          <span className="font-mono text-[13px] text-ink flex items-center gap-1.5">
            {row.values[highlight] !== "N/A" && (
              <Check className="h-3.5 w-3.5 text-emerald-600" />
            )}
            {row.values[highlight]}
          </span>
        </li>
      ))}
    </ul>
  );
}
