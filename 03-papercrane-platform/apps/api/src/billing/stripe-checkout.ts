/**
 * High-level Stripe Checkout helpers used by `apps/api/src/routes/billing.ts`.
 *
 * The low-level `createCheckoutSession` in `@papercrane/billing` only knows
 * about a raw `priceId`. Callers from the UI think in terms of
 *   { tier: 'pro', interval: 'monthly' }   — for subscriptions
 *   { pack: 'seeds_10k', quantity: 1 }     — for one-time top-ups
 * so this module owns the env → price-id mapping and the
 * subscription-vs-payment mode switch.
 *
 * Why a separate file instead of growing `@papercrane/billing/checkout.ts`?
 * --------------------------------------------------------------------------
 * `@papercrane/billing` is a pure domain package — it must not read
 * `process.env`. The price → tier mapping lives in `tiers.ts` there, but the
 * "which env var holds which Stripe price id" decision belongs to the API
 * service. Keeping it here lets us evolve the request shape (add yearly
 * packs, regional prices, etc.) without touching the shared package.
 */

import {
  createCheckoutSession as createStripeCheckoutSession,
  type BillingPriceEnv,
  type CheckoutSessionResult,
  type Stripe,
} from "@papercrane/billing";

export type CheckoutTier = "pro";
export type CheckoutInterval = "monthly" | "annual";
export type CheckoutPack = "seeds_10k";

export interface SubscriptionCheckoutInput {
  kind: "subscription";
  tier: CheckoutTier;
  interval: CheckoutInterval;
}

export interface PackCheckoutInput {
  kind: "pack";
  pack: CheckoutPack;
  quantity?: number;
}

export type CheckoutInput = SubscriptionCheckoutInput | PackCheckoutInput;

export interface BuildCheckoutSessionArgs {
  orgId: string;
  input: CheckoutInput;
  successUrl: string;
  cancelUrl: string;
  stripeCustomerId?: string | null;
  customerEmail?: string;
  priceEnv: BillingPriceEnv;
}

export interface BuildCheckoutDeps {
  stripe: Stripe;
}

export class CheckoutConfigError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
    this.name = "CheckoutConfigError";
  }
}

/**
 * Resolve the Stripe price id for a subscription tier+interval pair from the
 * env mapping. Throws a typed error so the route handler can map it to a 400
 * with a stable error code.
 */
export function resolveSubscriptionPriceId(
  tier: CheckoutTier,
  interval: CheckoutInterval,
  env: BillingPriceEnv,
): string {
  if (tier === "pro" && interval === "monthly") {
    if (!env.STRIPE_PRICE_PRO_MONTHLY) {
      throw new CheckoutConfigError(
        "STRIPE_PRICE_PRO_MONTHLY is not configured",
        "missing_price_pro_monthly",
      );
    }
    return env.STRIPE_PRICE_PRO_MONTHLY;
  }
  if (tier === "pro" && interval === "annual") {
    if (!env.STRIPE_PRICE_PRO_ANNUAL) {
      throw new CheckoutConfigError(
        "STRIPE_PRICE_PRO_ANNUAL is not configured",
        "missing_price_pro_annual",
      );
    }
    return env.STRIPE_PRICE_PRO_ANNUAL;
  }
  throw new CheckoutConfigError(
    `unsupported tier/interval: ${tier}/${interval}`,
    "unsupported_tier",
  );
}

export function resolvePackPriceId(
  pack: CheckoutPack,
  env: BillingPriceEnv,
): string {
  if (pack === "seeds_10k") {
    if (!env.STRIPE_PRICE_PACK_10K) {
      throw new CheckoutConfigError(
        "STRIPE_PRICE_PACK_10K is not configured",
        "missing_price_pack_10k",
      );
    }
    return env.STRIPE_PRICE_PACK_10K;
  }
  throw new CheckoutConfigError(
    `unsupported seed pack: ${pack}`,
    "unsupported_pack",
  );
}

/**
 * Build a Stripe Checkout session for either a subscription or a one-time
 * seed pack purchase. Returns the same `{ id, url }` shape regardless of mode
 * so the route handler stays uniform.
 *
 * Subscription mode delegates to `@papercrane/billing.createCheckoutSession`.
 * Pack mode (`mode: 'payment'`) is built locally because the shared helper
 * is hard-coded to `mode: 'subscription'` and changing it would ripple
 * through the webhook handlers — a subscription event must update the org
 * tier; a one-time payment must NOT.
 */
export async function buildCheckoutSession(
  args: BuildCheckoutSessionArgs,
  deps: BuildCheckoutDeps,
): Promise<CheckoutSessionResult> {
  const { input, priceEnv, orgId, successUrl, cancelUrl } = args;

  if (input.kind === "subscription") {
    const priceId = resolveSubscriptionPriceId(
      input.tier,
      input.interval,
      priceEnv,
    );
    return createStripeCheckoutSession(
      {
        orgId,
        priceId,
        successUrl,
        cancelUrl,
        stripeCustomerId: args.stripeCustomerId ?? null,
        customerEmail: args.customerEmail,
      },
      { stripe: deps.stripe },
    );
  }

  // Pack mode — one-time payment.
  const priceId = resolvePackPriceId(input.pack, priceEnv);
  const quantity = clampQuantity(input.quantity ?? 1);

  const params: Stripe.Checkout.SessionCreateParams = {
    mode: "payment",
    line_items: [{ price: priceId, quantity }],
    success_url: successUrl,
    cancel_url: cancelUrl,
    client_reference_id: orgId,
    metadata: { orgId, kind: "seed_pack", pack: input.pack },
    payment_intent_data: {
      metadata: { orgId, kind: "seed_pack", pack: input.pack },
    },
    allow_promotion_codes: true,
    billing_address_collection: "auto",
  };

  if (args.stripeCustomerId) {
    params.customer = args.stripeCustomerId;
  } else if (args.customerEmail) {
    params.customer_email = args.customerEmail;
  }

  const session = await deps.stripe.checkout.sessions.create(params);
  if (!session.url) {
    throw new Error("Stripe returned a session without a URL");
  }
  return { id: session.id, url: session.url };
}

function clampQuantity(q: number): number {
  if (!Number.isFinite(q) || q < 1) return 1;
  if (q > 100) return 100;
  return Math.floor(q);
}
