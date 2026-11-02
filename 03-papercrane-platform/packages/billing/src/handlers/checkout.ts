import type Stripe from "stripe";
import type { WebhookContext } from "../webhooks.js";

/**
 * Handle checkout.session.completed.
 *
 * This is the first event that links a Stripe Customer id to one of our
 * orgs — the user just finished Pro checkout and we know both:
 *   - session.client_reference_id → orgId (set by createCheckoutSession)
 *   - session.customer            → the new or existing Stripe Customer id
 *
 * We pre-create the Subscription row here so that the subsequent
 * customer.subscription.created event can be matched via stripe_customer_id
 * without needing to fall back on metadata. Tier-sync is a no-op at this
 * point — the subscription handler does the tier update once the
 * subscription is fully provisioned.
 *
 * If the session is NOT a subscription (one-shot seed-pack Checkout), we
 * still log, but do not create/update a Subscription row.
 */

export async function handleCheckoutCompleted(
  event: Stripe.Event,
  ctx: WebhookContext,
): Promise<void> {
  const session = event.data.object as Stripe.Checkout.Session;

  const orgId = session.client_reference_id ?? session.metadata?.orgId ?? null;
  const customerId =
    typeof session.customer === "string"
      ? session.customer
      : session.customer?.id ?? null;
  const subscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription?.id ?? null;

  if (!orgId) {
    ctx.logger.warn(
      { eventId: event.id, sessionId: session.id },
      "billing.checkout: no orgId on session; cannot link customer",
    );
    return;
  }

  if (!customerId) {
    ctx.logger.warn(
      { eventId: event.id, sessionId: session.id, orgId },
      "billing.checkout: session completed without a customer id",
    );
    return;
  }

  if (session.mode !== "subscription" || !subscriptionId) {
    // One-shot payments (seed packs) don't create a subscription — we only
    // record the customer link so we can create portal sessions later.
    ctx.logger.info(
      {
        eventId: event.id,
        sessionId: session.id,
        orgId,
        customerId,
        mode: session.mode,
      },
      "billing.checkout: non-subscription session completed",
    );
    return;
  }

  // Pre-link: upsert a Subscription row with tier=free until the actual
  // customer.subscription.created event arrives. The subscription row's
  // `tier` is re-derived from the real price at that point. We do it this
  // way so the customer id is present for the next event's lookup.
  //
  // `status=incomplete` is Stripe's own label for subs mid-provisioning.
  await ctx.prisma.subscription.upsert({
    where: { stripeSubscriptionId: subscriptionId },
    create: {
      orgId,
      stripeCustomerId: customerId,
      stripeSubscriptionId: subscriptionId,
      status: "incomplete",
      tier: "free",
      // Placeholder — overwritten by customer.subscription.created.
      currentPeriodEnd: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
    },
    update: {
      stripeCustomerId: customerId,
    },
  });

  ctx.logger.info(
    {
      eventId: event.id,
      sessionId: session.id,
      orgId,
      customerId,
      subscriptionId,
    },
    "billing.checkout: linked Stripe customer to org",
  );
}
