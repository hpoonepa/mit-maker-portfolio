"use client";

import { useState } from "react";
import { CreditCard, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

/**
 * "Manage billing" button: calls `billing.createPortalSession` and
 * redirects the user to the Stripe-hosted Customer Portal. The portal is
 * where they update card info, download invoices, change plan, or cancel.
 *
 * Hides itself on Free tier (no Stripe customer yet): except when the
 * caller passes `force` for tests.
 */

export interface ManageBillingButtonProps {
  /** Path the user returns to from the portal. Defaults to `/app/billing`. */
  returnPath?: string;
  /** Visual variant. */
  variant?: "primary" | "secondary";
  /** Override label. */
  label?: string;
  /** Render even if the org is on Free / has no customer yet. */
  force?: boolean;
  /** Test hook. */
  "data-testid"?: string;
}

export function ManageBillingButton({
  returnPath,
  variant = "secondary",
  label = "Manage billing",
  force = false,
  ...rest
}: ManageBillingButtonProps) {
  const [error, setError] = useState<string | null>(null);
  const subscription = trpc.billing.currentSubscription.useQuery(undefined, {
    staleTime: 60_000,
  });

  const mutation = trpc.billing.createPortalSession.useMutation({
    onSuccess: (data) => {
      if (data?.url) {
        window.location.href = data.url;
      } else {
        setError("Portal session response missing url");
      }
    },
    onError: (err) => {
      setError(err.message ?? "Could not open billing portal");
    },
  });

  const hasCustomer = Boolean(subscription.data?.stripeCustomerId);
  if (!force && !hasCustomer) return null;

  const onClick = () => {
    setError(null);
    mutation.mutate(returnPath ? { returnPath } : {});
  };

  const submitting = mutation.isPending;

  const className =
    variant === "primary"
      ? "inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90 disabled:opacity-60"
      : "inline-flex items-center gap-2 rounded-full border border-lattice px-5 py-2.5 font-sans text-[13px] text-ink hover:bg-paper-fold/50 disabled:opacity-60";

  return (
    <div className="inline-flex flex-col items-start gap-1.5">
      <button
        type="button"
        onClick={onClick}
        disabled={submitting}
        data-testid={rest["data-testid"] ?? "manage-billing-button"}
        className={className}
      >
        {submitting ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <CreditCard className="h-3.5 w-3.5" />
        )}
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
