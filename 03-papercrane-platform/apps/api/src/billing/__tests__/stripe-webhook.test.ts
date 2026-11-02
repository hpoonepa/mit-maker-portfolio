import Fastify from "fastify";
import sensible from "@fastify/sensible";
import { describe, expect, it, vi } from "vitest";
import type Stripe from "stripe";
import { registerBillingRoutes } from "../../routes/rest/billing.js";
import { handleWebhookEvent, type WebhookContext } from "@papercrane/billing";

/**
 * Stripe webhook handler — POST /v1/billing/webhook.
 *
 * Coverage:
 *   - Signature verification: bad sig → 400, missing header → 400, valid → 200
 *   - Event routing: customer.subscription.created promotes to Pro
 *   - invoice.payment_failed marks subscription past_due (dunning window)
 *   - Idempotency: same event id processed twice → single dispatch
 *
 * The Stripe SDK is fully mocked. The dispatcher (`handleWebhookEvent`) is
 * tested directly with stubbed handler seams so we don't reach the DB.
 */

const PRICE_ENV = {
  STRIPE_PRICE_PRO_MONTHLY: "price_pro_monthly_test",
  STRIPE_PRICE_PRO_ANNUAL: "price_pro_annual_test",
  STRIPE_PRICE_SEAT_ADDON: "price_seat_addon_test",
  STRIPE_PRICE_PACK_10K: "price_pack_10k_test",
};

function mkStripeStub(overrides?: {
  constructEvent?: ReturnType<typeof vi.fn>;
}) {
  return {
    checkout: { sessions: { create: vi.fn() } },
    billingPortal: { sessions: { create: vi.fn() } },
    webhooks: {
      constructEvent: overrides?.constructEvent ?? vi.fn(),
    },
  };
}

function mkEvent<T extends string>(
  type: T,
  id: string,
  data: unknown,
): Stripe.Event {
  return {
    id,
    type,
    object: "event",
    api_version: "2024-06-20",
    created: Math.floor(Date.now() / 1000),
    data: { object: data as never },
    livemode: false,
    pending_webhooks: 0,
    request: { id: null, idempotency_key: null },
  } as unknown as Stripe.Event;
}

async function buildApp(opts: {
  stripe?: ReturnType<typeof mkStripeStub>;
  redis?: { set: ReturnType<typeof vi.fn> } | null;
  webhookSecret?: string;
}) {
  const app = Fastify({ logger: false });
  await app.register(sensible);
  await registerBillingRoutes(app, {
    prisma: {
      $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
        fn({ subscription: { findUnique: vi.fn().mockResolvedValue(null) } }),
      ),
    } as never,
    redis: (opts.redis ?? null) as never,
    stripe: (opts.stripe ?? mkStripeStub()) as never,
    priceEnv: PRICE_ENV,
    webhookSecret: opts.webhookSecret ?? "whsec_test",
  });
  return app;
}

function mkCtx(opts: {
  redisFirst?: boolean;
  handlers?: Partial<WebhookContext["handlers"]>;
} = {}): WebhookContext {
  const set = vi
    .fn()
    .mockResolvedValue(opts.redisFirst === false ? null : "OK");
  return {
    prisma: {} as never,
    redis: { set } as never,
    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    } as never,
    priceEnv: PRICE_ENV,
    handlers: {
      onSubscriptionEvent: vi.fn().mockResolvedValue(undefined),
      onInvoiceEvent: vi.fn().mockResolvedValue(undefined),
      onCheckoutCompleted: vi.fn().mockResolvedValue(undefined),
      ...opts.handlers,
    },
  };
}

describe("POST /v1/billing/webhook — signature verification", () => {
  it("rejects requests without a Stripe-Signature header", async () => {
    const app = await buildApp({});
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ id: "evt_x", type: "noop" }),
    });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toMatchObject({ error: "invalid_signature" });
    await app.close();
  });

  it("rejects bad signatures with 400 and does NOT dispatch", async () => {
    const constructEvent = vi.fn().mockImplementation(() => {
      throw new Error("No signatures found matching the expected signature");
    });
    const app = await buildApp({
      stripe: mkStripeStub({ constructEvent }),
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: {
        "content-type": "application/json",
        "stripe-signature": "t=1,v1=tampered",
      },
      payload: JSON.stringify({ id: "evt_bad", type: "anything" }),
    });
    expect(res.statusCode).toBe(400);
    expect(constructEvent).toHaveBeenCalledTimes(1);
    await app.close();
  });

  it("accepts a valid signature, preserves raw bytes, returns 200", async () => {
    // Stripe HMAC requires byte-exact body. The raw-body parser must hand the
    // untouched Buffer to constructEvent — re-serialised JSON would fail.
    const fakeEvent = mkEvent("checkout.session.completed", "evt_good", {
      id: "cs_1",
      customer: "cus_1",
      mode: "subscription",
    });
    const constructEvent = vi.fn().mockReturnValue(fakeEvent);
    const redisSet = vi.fn().mockResolvedValue("OK");
    const app = await buildApp({
      stripe: mkStripeStub({ constructEvent }),
      redis: { set: redisSet },
    });
    const payload = JSON.stringify({ id: "evt_good", type: fakeEvent.type });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: {
        "content-type": "application/json",
        "stripe-signature": "t=1,v1=valid",
      },
      payload,
    });
    expect(res.statusCode).toBe(200);
    const args = constructEvent.mock.calls[0]!;
    expect(Buffer.isBuffer(args[0])).toBe(true);
    expect((args[0] as Buffer).toString("utf8")).toBe(payload);
    expect(args[1]).toBe("t=1,v1=valid");
    expect(args[2]).toBe("whsec_test");
    await app.close();
  });
});

describe("handleWebhookEvent — subscription lifecycle", () => {
  it("routes customer.subscription.created → onSubscriptionEvent (Pro promotion)", async () => {
    const ctx = mkCtx();
    const event = mkEvent("customer.subscription.created", "evt_pro_promote", {
      id: "sub_1",
      customer: "cus_1",
      status: "active",
      items: {
        data: [{ price: { id: PRICE_ENV.STRIPE_PRICE_PRO_MONTHLY } }],
      },
      metadata: { orgId: "org_1" },
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).toHaveBeenCalledTimes(1);
    expect(ctx.handlers.onInvoiceEvent).not.toHaveBeenCalled();
    expect(ctx.handlers.onCheckoutCompleted).not.toHaveBeenCalled();
    // The subscription handler is responsible for the Pro tier write; we
    // assert it was invoked with the original event so its own unit tests
    // cover the DB writes.
    const call = (ctx.handlers.onSubscriptionEvent as ReturnType<typeof vi.fn>)
      .mock.calls[0]!;
    expect(call[0]).toBe(event);
  });

  it("routes invoice.payment_failed → onInvoiceEvent (dunning past_due)", async () => {
    const ctx = mkCtx();
    const event = mkEvent("invoice.payment_failed", "evt_dunning", {
      id: "in_failed",
      customer: "cus_1",
      subscription: "sub_1",
      status: "open",
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onInvoiceEvent).toHaveBeenCalledTimes(1);
    // Subscription.deleted (final downgrade) arrives separately after Stripe
    // smart-retries exhaust; this test only covers the past_due signal.
    expect(ctx.handlers.onSubscriptionEvent).not.toHaveBeenCalled();
  });

  it("routes customer.subscription.deleted → onSubscriptionEvent (post-dunning Free downgrade)", async () => {
    const ctx = mkCtx();
    const event = mkEvent("customer.subscription.deleted", "evt_downgrade", {
      id: "sub_1",
      customer: "cus_1",
      status: "canceled",
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).toHaveBeenCalledTimes(1);
  });
});

describe("handleWebhookEvent — idempotency (event_id replay)", () => {
  it("processes the first delivery and skips the second with the same event_id", async () => {
    // First delivery: SET NX returns "OK" → fresh, dispatch fires.
    // Second delivery: SET NX returns null → duplicate, dispatch skipped.
    const set = vi
      .fn()
      .mockResolvedValueOnce("OK")
      .mockResolvedValueOnce(null);
    const onSub = vi.fn().mockResolvedValue(undefined);
    const ctx: WebhookContext = {
      prisma: {} as never,
      redis: { set } as never,
      logger: {
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
        debug: vi.fn(),
      } as never,
      priceEnv: PRICE_ENV,
      handlers: {
        onSubscriptionEvent: onSub,
        onInvoiceEvent: vi.fn(),
        onCheckoutCompleted: vi.fn(),
      },
    };
    const event = mkEvent("customer.subscription.updated", "evt_replay_42", {
      id: "sub_replay",
      customer: "cus_1",
      status: "active",
    });

    await handleWebhookEvent(event, ctx);
    await handleWebhookEvent(event, ctx);

    // SET NX called twice (once per delivery), but handler only fires once.
    expect(set).toHaveBeenCalledTimes(2);
    expect(onSub).toHaveBeenCalledTimes(1);

    // Both calls used the same idempotency key (Stripe event id).
    expect(set.mock.calls[0]![0]).toBe("stripe:webhook:evt_replay_42");
    expect(set.mock.calls[1]![0]).toBe("stripe:webhook:evt_replay_42");
  });

  it("uses a 7-day TTL on the idempotency key (matches Stripe retry window)", async () => {
    const ctx = mkCtx();
    const event = mkEvent("customer.subscription.created", "evt_ttl_check", {
      id: "sub_1",
      customer: "cus_1",
      status: "active",
    });
    await handleWebhookEvent(event, ctx);
    const set = ctx.redis!.set as ReturnType<typeof vi.fn>;
    const args = set.mock.calls[0]!;
    expect(args[2]).toBe("EX");
    expect(args[3]).toBe(7 * 24 * 60 * 60); // 604800 seconds
    expect(args[4]).toBe("NX");
  });

  it("permits dispatch when Redis is unavailable (DB upsert is the second line of defense)", async () => {
    const onSub = vi.fn().mockResolvedValue(undefined);
    const ctx: WebhookContext = {
      prisma: {} as never,
      redis: null,
      logger: {
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
        debug: vi.fn(),
      } as never,
      priceEnv: PRICE_ENV,
      handlers: {
        onSubscriptionEvent: onSub,
        onInvoiceEvent: vi.fn(),
        onCheckoutCompleted: vi.fn(),
      },
    };
    const event = mkEvent("customer.subscription.created", "evt_no_redis", {
      id: "sub_x",
      customer: "cus_1",
      status: "active",
    });
    await handleWebhookEvent(event, ctx);
    expect(onSub).toHaveBeenCalledTimes(1);
  });
});
