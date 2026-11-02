import type Stripe from "stripe";
import type { PrismaClient } from "@papercrane/db";
import type { BillingPriceEnv } from "./tiers.js";
import { handleSubscriptionEvent } from "./handlers/subscription.js";
import { handleInvoiceEvent } from "./handlers/invoice.js";
import { handleCheckoutCompleted } from "./handlers/checkout.js";

/**
 * Webhook dispatcher.
 *
 * Stripe delivers events at-least-once. Two defenses against double-processing:
 *   1. Redis-backed idempotency (this file): `SET NX EX 7d` on the event id.
 *      If the key already existed we skip dispatch entirely. 7-day TTL matches
 *      Stripe's retry window.
 *   2. Per-handler DB idempotency: subscription writes are upserts keyed on
 *      stripe_subscription_id, so the row is convergent even if step 1 is
 *      bypassed (e.g. Redis outage with `skipIdempotency` = true).
 *
 * This module does NOT do signature verification — that lives in
 * `verifySignature.ts` and runs before the event is handed to the dispatcher.
 * Keeping them separate means the API route can return 400 for bad sig vs.
 * 200 for unhandled events without mixing concerns.
 */

export interface WebhookLogger {
  debug(obj: unknown, msg?: string): void;
  info(obj: unknown, msg?: string): void;
  warn(obj: unknown, msg?: string): void;
  error(obj: unknown, msg?: string): void;
}

/**
 * Minimal ioredis surface we actually use. Keeping it narrow makes the tests
 * easy (vi.fn()) and avoids bundling ioredis as a dep of this package.
 */
export interface WebhookRedis {
  set(
    key: string,
    value: string,
    mode1: "EX",
    ttlSeconds: number,
    mode2: "NX",
  ): Promise<"OK" | null>;
}

export interface WebhookHandlerSeam {
  onSubscriptionEvent: (
    event: Stripe.Event,
    ctx: WebhookContext,
  ) => Promise<void>;
  onInvoiceEvent: (
    event: Stripe.Event,
    ctx: WebhookContext,
  ) => Promise<void>;
  onCheckoutCompleted: (
    event: Stripe.Event,
    ctx: WebhookContext,
  ) => Promise<void>;
}

export interface WebhookContext {
  prisma: PrismaClient;
  redis: WebhookRedis | null;
  logger: WebhookLogger;
  priceEnv: BillingPriceEnv;
  /**
   * Injectable handler seam — real code wires the `handlers/*` exports, tests
   * pass vi.fn() stubs so dispatch logic is tested in isolation from DB.
   */
  handlers: WebhookHandlerSeam;
}

/** Convenience: build a default context handler seam wired to the real handlers. */
export const defaultHandlers: WebhookHandlerSeam = {
  onSubscriptionEvent: handleSubscriptionEvent,
  onInvoiceEvent: handleInvoiceEvent,
  onCheckoutCompleted: handleCheckoutCompleted,
};

const IDEMPOTENCY_KEY_PREFIX = "stripe:webhook:";
const IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60;

/**
 * Check-and-set the idempotency marker for this event. Returns true if this
 * is the first time we've seen the event (caller should dispatch). Returns
 * false on duplicate.
 *
 * If Redis is unavailable (null) we permit dispatch — the DB upserts in
 * individual handlers provide a second line of defense.
 */
async function markProcessed(
  eventId: string,
  redis: WebhookRedis | null,
  logger: WebhookLogger,
): Promise<boolean> {
  if (!redis) {
    logger.warn(
      { eventId },
      "billing.webhook: redis not configured, skipping idempotency check",
    );
    return true;
  }
  const key = `${IDEMPOTENCY_KEY_PREFIX}${eventId}`;
  const res = await redis.set(key, "1", "EX", IDEMPOTENCY_TTL_SECONDS, "NX");
  return res === "OK";
}

export async function handleWebhookEvent(
  event: Stripe.Event,
  ctx: WebhookContext,
): Promise<void> {
  const fresh = await markProcessed(event.id, ctx.redis, ctx.logger);
  if (!fresh) {
    ctx.logger.info(
      { eventId: event.id, eventType: event.type },
      "billing.webhook: duplicate event, skipping",
    );
    return;
  }

  ctx.logger.info(
    { eventId: event.id, eventType: event.type },
    "billing.webhook: dispatching",
  );

  switch (event.type) {
    case "customer.subscription.created":
    case "customer.subscription.updated":
    case "customer.subscription.deleted":
      await ctx.handlers.onSubscriptionEvent(event, ctx);
      return;

    case "invoice.paid":
    case "invoice.payment_failed":
      await ctx.handlers.onInvoiceEvent(event, ctx);
      return;

    case "checkout.session.completed":
      await ctx.handlers.onCheckoutCompleted(event, ctx);
      return;

    default:
      // Unhandled types are logged and acked. Stripe will stop retrying once
      // we return 200; any we care about should be enumerated explicitly above.
      ctx.logger.debug(
        { eventId: event.id, eventType: event.type },
        "billing.webhook: no handler for event type",
      );
      return;
  }
}
