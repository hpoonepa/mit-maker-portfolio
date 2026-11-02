"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

/**
 * Direct "Upgrade to Pro" button that calls the typed
 * `billing.createCheckoutSession` tRPC mutation and redirects via
 * `window.location.href`. Stripe never gets touched from the browser bundle
 *: the API resolves the env-pinned price id server-side.
 *
 * For the multi-step modal with cadence picker + feature comparison see
 * `UpgradeModal.tsx`. This button is the one-click variant used from
 * dashboards, success-page redirects, and gate banners where the user has
 * already chosen a cadence.
 */

export type UpgradeInterval = "monthly" | "annual";

export interface UpgradeButtonProps {
  /** Stripe billing cadence; defaults to monthly. */
  interval?: UpgradeInterval;
  /** Path the user returns to after Stripe Checkout. */
  returnPath?: string;
  /** Visual variant. */
  variant?: "primary" | "secondary";
  /** Override label. */
  label?: string;
  /** Disable for testing or when the org is already Pro. */
  disabled?: boolean;
  /** Test hook. */
  "data-testid"?: string;
}

export function UpgradeButton({
  interval = "monthly",
  returnPath,
  variant = "primary",
  label = "Upgrade to Pro",
  disabled = false,
  ...rest
}: UpgradeButtonProps) {
  const [error, setError] = useState<string | null>(null);
  const mutation = trpc.billing.createCheckoutSession.useMutation({
    onSuccess: (data) => {
      if (data?.url) {
        window.location.href = data.url;
      } else {
        setError("Checkout session response missing url");
      }
    },
    onError: (err) => {
      setError(err.message ?? "Could not start checkout");
    },
  });

  const onClick = () => {
    setError(null);
    mutation.mutate({
      tier: "pro",
      interval,
      ...(returnPath ? { returnPath } : {}),
    });
  };

  const submitting = mutation.isPending;
  const isDisabled = disabled || submitting;

  const className =
    variant === "primary"
      ? "inline-flex items-center gap-2 rounded-md bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90 disabled:opacity-60"
      : "inline-flex items-center gap-2 rounded-md border border-lattice px-5 py-2.5 font-sans text-[13px] text-ink hover:bg-paper-fold/50 disabled:opacity-60";

  return (
    <div className="inline-flex flex-col items-start gap-1.5">
      <button
        type="button"
        onClick={onClick}
        disabled={isDisabled}
        data-testid={rest["data-testid"] ?? "upgrade-button"}
        className={className}
      >
        {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {label}
      </button>
      {error && (
        <span className="font-sans text-[12px] text-red-600" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
