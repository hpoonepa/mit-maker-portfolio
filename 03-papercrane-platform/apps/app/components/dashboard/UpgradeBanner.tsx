"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

type UpgradeBannerProps = {
  /** Forecast as a fraction of cap (1.1 = 110%). */
  forecastPctOfCap: number;
  /** Current org tier, used to pick the CTA copy. */
  tier: "free" | "pro" | "frontier";
  /** Optional override for the link target. */
  href?: string;
  className?: string;
};

/**
 * Shown when the projected end-of-period spend exceeds 110% of the plan
 * cap. Free orgs are nudged to Pro, Pro orgs to Frontier or a top-up
 * pack. Frontier orgs (soft cap) get a quieter notice.
 */
export function UpgradeBanner({
  forecastPctOfCap,
  tier,
  href,
  className,
}: UpgradeBannerProps) {
  if (forecastPctOfCap <= 1.1) return null;

  const overshoot = Math.round((forecastPctOfCap - 1) * 100);

  const copy =
    tier === "free"
      ? {
          headline: "You're on track to exceed Free's 500-seed cap.",
          body: `At your current pace you'll hit ~${overshoot}% over plan this period. Upgrade to Pro for 50,000 seeds, managed GPU, and 20× concurrency.`,
          cta: "Upgrade to Pro · $299/mo",
          target: href ?? "/billing/upgrade",
        }
      : tier === "pro"
        ? {
            headline: "Forecast exceeds your Pro plan cap.",
            body: `You're tracking ~${overshoot}% over the 50,000 seed allotment. Add a top-up pack now or move to Frontier for unlimited (soft 1M) seeds and dedicated capacity.`,
            cta: "Buy a top-up pack",
            target: href ?? "/billing/upgrade",
          }
        : {
            headline: "Approaching Frontier soft cap (1M seeds).",
            body: `Your account is forecast to land ~${overshoot}% over the soft cap. Reach out to your account manager to renegotiate the contract ceiling.`,
            cta: "Contact account team",
            target: href ?? "/billing/upgrade",
          };

  return (
    <Link
      href={copy.target}
      className={cn(
        "group flex flex-col gap-4 rounded-2xl border border-lattice-strong bg-paper p-5 md:flex-row md:items-center md:justify-between",
        className,
      )}
    >
      <div>
        <p className="font-sans text-[12px] font-medium text-crane-deep">
          Usage forecast
        </p>
        <h3 className="mt-1 font-sans text-[15px] font-medium text-ink">
          {copy.headline}
        </h3>
        <p className="mt-1 max-w-2xl font-sans text-[13px] leading-5 text-graphite">
          {copy.body}
        </p>
      </div>

      <span className="inline-flex shrink-0 items-center gap-2 self-start rounded-md bg-ink px-4 py-2.5 font-sans text-[12px] font-medium text-paper md:self-auto">
        {copy.cta}
        <ArrowRight size={14} aria-hidden="true" />
      </span>
    </Link>
  );
}
