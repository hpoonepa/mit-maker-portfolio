import type Stripe from "stripe";
import type {
  SubscriptionStatus as PrismaSubscriptionStatus,
  OrgTier,
} from "@papercrane/db";
import type { WebhookContext } from "../webhooks.js";
import {
  resolvePriceConfig,
  isProPrice,
  freePriceConfig,
  freeTierFlags,
  type PriceConfig,
} from "../tiers.js";

/**
 * Handle customer.subscription.{created,updated,deleted}.
 *
 * Each event delivers the full current state of the Subscription object, so
 * we can treat create/update the same way and only special-case delete
 * (which we translate into "downgrade the org to Free").
 *
 * Sequence:
 *   1. Find the org via `stripe_customer_id` on the existing Subscription row,
 *      or via `metadata.orgId` on the Subscription if we haven't linked yet
 *      (possible if checkout.session.completed lost a race with
 *      customer.subscription.created — Stripe can deliver them out-of-order).
 *   2. Derive the target tier from the Subscription's line items — ignoring
 *      seat add-ons and seed packs (they ride on top of a Pro plan).
 *   3. Upsert the Subscription row (unique on stripe_subscription_id).
 *   4. Update Organization.tier + seeds_quota + retention_days.
 *   5. Upsert FeatureFlag row with the new tier's flag deltas.
 *
 * Idempotency: the upserts are keyed on stable Stripe ids. Re-delivery of the
 * same event produces the same terminal state.
 */

type LineItemPrice = { id: string };

function pickDrivingPrice(
  subscription: Stripe.Subscription,
  env: WebhookContext["priceEnv"],
): string | null {
  // Subscriptions can have multiple items — Pro base + seat add-on. Prefer a
  // Pro-tier price when present; fall back to the first item if nothing else
  // matches (degrades gracefully for seed-pack-only / non-tier subscriptions
  // which we treat as "no tier change").
  const items = subscription.items?.data ?? [];
  for (const item of items) {
    const priceId = (item.price as LineItemPrice | undefined)?.id;
    if (priceId && isProPrice(priceId, env)) return priceId;
  }
  const firstPrice = items[0]?.price as LineItemPrice | undefined;
  return firstPrice?.id ?? null;
}

function mapStripeStatus(status: Stripe.Subscription.Status): PrismaSubscriptionStatus {
  // Prisma enum matches Stripe's string values 1:1 except for casing. Stripe
  // uses snake_case; our enum does too. Stripe has a few we don't list (e.g.
  // "paused" is in Stripe and in Prisma; we carry all of them).
  switch (status) {
    case "trialing":
    case "active":
    case "past_due":
    case "canceled":
    case "incomplete":
    case "incomplete_expired":
    case "unpaid":
    case "paused":
      return status;
    default:
      // Future-proofing: if Stripe adds a status we don't know, fall back to
      // "unpaid" which is safe (won't grant Pro).
      return "unpaid";
  }
}

async function resolveOrgId(
  subscription: Stripe.Subscription,
  ctx: WebhookContext,
): Promise<string | null> {
  const customerId =
    typeof subscription.customer === "string"
      ? subscription.customer
      : subscription.customer?.id;
  if (!customerId) return null;

  // Fast path: existing Subscription row keyed on customer id.
  const existing = await ctx.prisma.subscription.findUnique({
    where: { stripeCustomerId: customerId },
    select: { orgId: true },
  });
  if (existing) return existing.orgId;

  // Slow path: checkout.session.completed may not have landed yet. Fall back
  // to the subscription metadata we set in checkout.ts.
  const metaOrgId = subscription.metadata?.orgId;
  if (metaOrgId) return metaOrgId;

  return null;
}

async function applyTierState(
  orgId: string,
  target: PriceConfig,
  ctx: WebhookContext,
): Promise<void> {
  // Organization — tier + quota + retention live here.
  await ctx.prisma.organization.update({
    where: { id: orgId },
    data: {
      tier: target.tier as OrgTier,
      seedsQuota: target.seedsQuota,
      retentionDays: target.flags.retentionDays,
    },
  });

  // FeatureFlag — upsert so freshly-paid orgs get a row the first time.
  await ctx.prisma.featureFlag.upsert({
    where: { orgId },
    create: {
      orgId,
      retentionDays: target.flags.retentionDays,
      maxConcurrent: target.flags.maxConcurrent,
      closedWeightsAllowed: target.flags.closedWeightsAllowed,
      vpcEnabled: target.flags.vpcEnabled,
      byocRequired: target.flags.byocRequired,
    },
    update: {
      retentionDays: target.flags.retentionDays,
      maxConcurrent: target.flags.maxConcurrent,
      closedWeightsAllowed: target.flags.closedWeightsAllowed,
      vpcEnabled: target.flags.vpcEnabled,
      byocRequired: target.flags.byocRequired,
    },
  });
}

export async function handleSubscriptionEvent(
  event: Stripe.Event,
  ctx: WebhookContext,
): Promise<void> {
  const subscription = event.data.object as Stripe.Subscription;
  const orgId = await resolveOrgId(subscription, ctx);
  if (!orgId) {
    ctx.logger.warn(
      {
        eventId: event.id,
        eventType: event.type,
        subscriptionId: subscription.id,
        customerId:
          typeof subscription.customer === "string"
            ? subscription.customer
            : subscription.customer?.id,
      },
      "billing.subscription: could not resolve orgId; skipping",
    );
    return;
  }

  const customerId =
    typeof subscription.customer === "string"
      ? subscription.customer
      : subscription.customer?.id ?? "";

  const isDelete = event.type === "customer.subscription.deleted";

  // On delete, downgrade to Free regardless of line items. On create/update
  // look at the driving price to decide whether this subscription grants Pro.
  let target: PriceConfig;
  if (isDelete) {
    target = freePriceConfig;
  } else {
    const drivingPrice = pickDrivingPrice(subscription, ctx.priceEnv);
    const priceCfg = drivingPrice
      ? resolvePriceConfig(drivingPrice, ctx.priceEnv)
      : null;
    if (!priceCfg) {
      // Subscription exists but its only prices are non-tier (seat add-on,
      // seed pack). Don't change the org's tier; just log.
      ctx.logger.info(
        {
          eventId: event.id,
          subscriptionId: subscription.id,
          drivingPrice,
        },
        "billing.subscription: no tier-changing price on subscription, skipping tier sync",
      );
      return;
    }
    target = priceCfg;
  }

  const periodEnd = new Date(
    (subscription.current_period_end ?? Math.floor(Date.now() / 1000)) * 1000,
  );

  // Upsert the Subscription mirror row. On delete we keep the row for audit
  // but flip its status/tier to canceled + free.
  await ctx.prisma.subscription.upsert({
    where: { stripeSubscriptionId: subscription.id },
    create: {
      orgId,
      stripeCustomerId: customerId,
      stripeSubscriptionId: subscription.id,
      status: mapStripeStatus(subscription.status),
      tier: target.tier as OrgTier,
      currentPeriodEnd: periodEnd,
    },
    update: {
      status: mapStripeStatus(subscription.status),
      tier: target.tier as OrgTier,
      currentPeriodEnd: periodEnd,
    },
  });

  await applyTierState(orgId, target, ctx);

  ctx.logger.info(
    {
      eventId: event.id,
      eventType: event.type,
      orgId,
      subscriptionId: subscription.id,
      tier: target.tier,
      status: subscription.status,
    },
    "billing.subscription: tier sync complete",
  );
}

// Re-exported for tests that want to assert specific downgrade flag values.
export { freeTierFlags };
