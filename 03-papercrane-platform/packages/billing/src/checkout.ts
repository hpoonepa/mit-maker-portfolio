import type Stripe from "stripe";

/**
 * Create a Stripe Checkout session for a Pro subscription.
 *
 * When the org already has a `stripe_customer_id` we pass it as `customer`
 * so card details roll over and the webhook can match the session back to
 * the same Stripe Customer. On the very first Pro checkout the org has no
 * customer yet; Stripe creates one during the session and emits
 * `checkout.session.completed` with the new id, which our handler links
 * back to the org via `client_reference_id`.
 *
 * `client_reference_id` AND `metadata.orgId` are both set. `client_reference_id`
 * surfaces in checkout.session.completed; `metadata.orgId` is what we search
 * on if we ever need to look up from a Subscription or Invoice object that
 * doesn't include the session reference.
 */

export interface CreateCheckoutSessionArgs {
  orgId: string;
  priceId: string;
  successUrl: string;
  cancelUrl: string;
  /** Existing Stripe Customer id — if present, Stripe will reuse it. */
  stripeCustomerId?: string | null;
  /**
   * Email to pre-fill when creating a fresh customer. Ignored if
   * `stripeCustomerId` is set (Stripe rejects that combination).
   */
  customerEmail?: string;
}

export interface CheckoutDeps {
  stripe: Pick<Stripe, "checkout">;
}

export interface CheckoutSessionResult {
  id: string;
  url: string;
}

export async function createCheckoutSession(
  args: CreateCheckoutSessionArgs,
  deps: CheckoutDeps,
): Promise<CheckoutSessionResult> {
  const hasExistingCustomer = Boolean(args.stripeCustomerId);

  const params: Stripe.Checkout.SessionCreateParams = {
    mode: "subscription",
    line_items: [{ price: args.priceId, quantity: 1 }],
    success_url: args.successUrl,
    cancel_url: args.cancelUrl,
    client_reference_id: args.orgId,
    metadata: { orgId: args.orgId },
    // Pass metadata through to the created subscription so the webhook
    // handler can recover the orgId even if the session metadata was lost.
    subscription_data: {
      metadata: { orgId: args.orgId },
    },
    allow_promotion_codes: true,
    billing_address_collection: "auto",
  };

  if (hasExistingCustomer) {
    params.customer = args.stripeCustomerId!;
  } else if (args.customerEmail) {
    params.customer_email = args.customerEmail;
  }

  const session = await deps.stripe.checkout.sessions.create(params);
  if (!session.url) {
    throw new Error("Stripe returned a session without a URL");
  }
  return { id: session.id, url: session.url };
}
