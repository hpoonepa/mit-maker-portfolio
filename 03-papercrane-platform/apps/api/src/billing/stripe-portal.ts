/**
 * Stripe Customer Portal helper for `apps/api`.
 *
 * The portal is fully Stripe-hosted — invoice download, card update, plan
 * change, cancel — so all we do server-side is mint a one-shot portal URL.
 * The actual portal feature flags (allow cancel? allow plan change?) are
 * configured in the Stripe Dashboard, not here.
 *
 * This is a thin shim over `@papercrane/billing.createPortalSession` that
 * adds the precondition check (org must already have a Stripe Customer id —
 * a Free user who has never been to checkout has no portal). Throwing a
 * typed error here lets the route map it to a stable 409 with a code the
 * dashboard can render as "Subscribe first to manage billing".
 */

import {
  createPortalSession as createStripePortalSession,
  type PortalSessionResult,
  type Stripe,
} from "@papercrane/billing";

export interface BuildPortalSessionArgs {
  orgId: string;
  stripeCustomerId: string | null;
  returnUrl: string;
}

export interface BuildPortalDeps {
  stripe: Stripe;
}

export class PortalUnavailableError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = "PortalUnavailableError";
  }
}

export async function buildPortalSession(
  args: BuildPortalSessionArgs,
  deps: BuildPortalDeps,
): Promise<PortalSessionResult> {
  if (!args.stripeCustomerId) {
    throw new PortalUnavailableError(
      `org ${args.orgId} has no stripe customer yet`,
      "no_stripe_customer",
    );
  }
  return createStripePortalSession(
    {
      stripeCustomerId: args.stripeCustomerId,
      returnUrl: args.returnUrl,
    },
    { stripe: deps.stripe },
  );
}
