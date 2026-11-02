"use client";

import { useState } from "react";
import { UpgradeModal } from "./UpgradeModal";
import { useSubscription } from "@/lib/billing/useSubscription";

/**
 * Small button that opens the shared UpgradeModal. Use on Free-tier
 * surfaces (sidebar footer, premium-feature gate modals): it self-hides
 * for Pro / Frontier users so we don't show "Upgrade to Pro" to someone
 * already on Pro.
 *
 * Variants
 * --------
 *   inline  : text+icon, for gate modals / banners
 *   pill    : rounded button, for the sidebar
 *   card    : full-width promo card, for the empty-states on dashboards
 */

export interface UpgradeCTAProps {
  variant?: "inline" | "pill" | "card";
  /** Optional override label. */
  label?: string;
  /** Skip the subscription check (useful on public pages / tests). */
  force?: boolean;
}

export function UpgradeCTA({
  variant = "pill",
  label = "Upgrade to Pro",
  force = false,
}: UpgradeCTAProps) {
  const { data } = useSubscription();
  const [open, setOpen] = useState(false);

  const shouldShow = force || !data || data.isFree;
  if (!shouldShow) return null;

  const onClick = () => setOpen(true);

  let trigger: React.ReactNode;
  switch (variant) {
    case "inline":
      trigger = (
        <button
          type="button"
          onClick={onClick}
          data-testid="e2e-upgrade-cta"
          className="inline-flex items-center gap-1.5 font-sans text-[13px] text-ink underline decoration-ink/40 underline-offset-2 hover:decoration-ink"
        >
          {label}
        </button>
      );
      break;
    case "card":
      trigger = (
        <button
          type="button"
          onClick={onClick}
          data-testid="e2e-upgrade-cta"
          className="w-full rounded-lg border border-lattice bg-paper-fold/40 p-6 text-left hover:bg-paper-fold/60"
        >
          <p className="font-sans text-[12px] text-graphite-soft">
            Plan limits
          </p>
          <h3 className="mt-2 font-display text-[20px] text-ink tracking-[-0.01em]">
            {label}
          </h3>
          <p className="mt-1 font-sans text-[13px] text-graphite">
            50,000 seeds/mo, 90-day retention, 20 concurrent jobs.
          </p>
        </button>
      );
      break;
    case "pill":
    default:
      trigger = (
        <button
          type="button"
          onClick={onClick}
          data-testid="e2e-upgrade-cta"
          className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 font-sans text-[12px] text-paper hover:bg-ink/90"
        >
          {label}
        </button>
      );
  }

  return (
    <>
      {trigger}
      <UpgradeModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
