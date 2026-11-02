import type Stripe from "stripe";

/**
 * Stripe Customer Portal session.
 *
 * The portal is Stripe-hosted and handles self-serve billing — card updates,
 * invoice download, cancel, plan switch — so we just redirect. The portal
 * config (which products to show, whether cancels are allowed) lives in the
 * Stripe Dashboard, not here.
 */

export interface CreatePortalSessionArgs {
  stripeCustomerId: string;
  returnUrl: string;
}

export interface PortalDeps {
  stripe: Pick<Stripe, "billingPortal">;
}

export interface PortalSessionResult {
  id: string;
  url: string;
}

export async function createPortalSession(
  args: CreatePortalSessionArgs,
  deps: PortalDeps,
): Promise<PortalSessionResult> {
  if (!args.stripeCustomerId) {
    throw new Error("createPortalSession: stripeCustomerId is required");
  }
  const session = await deps.stripe.billingPortal.sessions.create({
    customer: args.stripeCustomerId,
    return_url: args.returnUrl,
  });
  return { id: session.id, url: session.url };
}
