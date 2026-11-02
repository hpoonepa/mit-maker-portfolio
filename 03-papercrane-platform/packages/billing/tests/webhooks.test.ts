import { describe, expect, it, vi } from "vitest";
import type Stripe from "stripe";
import { handleWebhookEvent } from "../src/webhooks.js";
import { verifyAndParseEvent } from "../src/verifySignature.js";
import type { WebhookContext } from "../src/webhooks.js";

/**
 * Webhook dispatch + signature verification.
 *
 * Dispatch is tested by stubbing the per-event handlers on the context's
 * `handlers` injection seam and asserting which one fires.
 *
 * Signature verification delegates to Stripe's SDK; we only assert that our
 * wrapper (a) returns the parsed event on a valid signature and (b) throws on
 * an invalid one. We drive both paths via a stubbed Stripe client whose
 * `webhooks.constructEvent` is under our control.
 */

function makeCtx(overrides: {
  redisFirst?: boolean;
  handlers?: Partial<WebhookContext["handlers"]>;
} = {}): WebhookContext {
  const redisSetNx = vi
    .fn()
    // SET NX returns "OK" on first-write, null on duplicate.
    .mockResolvedValue(overrides.redisFirst === false ? null : "OK");

  const handlers: WebhookContext["handlers"] = {
    onSubscriptionEvent: vi.fn().mockResolvedValue(undefined),
    onInvoiceEvent: vi.fn().mockResolvedValue(undefined),
    onCheckoutCompleted: vi.fn().mockResolvedValue(undefined),
    ...overrides.handlers,
  };

  return {
    prisma: {} as never,
    redis: { set: redisSetNx } as never,
    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    } as never,
    priceEnv: {
      STRIPE_PRICE_PRO_MONTHLY: "price_pro_monthly_test",
      STRIPE_PRICE_PRO_ANNUAL: "price_pro_annual_test",
      STRIPE_PRICE_SEAT_ADDON: "price_seat_addon_test",
      STRIPE_PRICE_PACK_10K: "price_pack_10k_test",
    },
    handlers,
  };
}

function mkEvent<T extends Stripe.Event.Type>(
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

describe("handleWebhookEvent — dispatch", () => {
  it("routes customer.subscription.created to the subscription handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent(
      "customer.subscription.created",
      "evt_sub_1",
      { id: "sub_1", customer: "cus_1", status: "active" },
    );
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).toHaveBeenCalledTimes(1);
    expect(ctx.handlers.onInvoiceEvent).not.toHaveBeenCalled();
    expect(ctx.handlers.onCheckoutCompleted).not.toHaveBeenCalled();
  });

  it("routes customer.subscription.updated to the subscription handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent(
      "customer.subscription.updated",
      "evt_sub_2",
      { id: "sub_1", customer: "cus_1", status: "past_due" },
    );
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).toHaveBeenCalledTimes(1);
  });

  it("routes customer.subscription.deleted to the subscription handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent(
      "customer.subscription.deleted",
      "evt_sub_3",
      { id: "sub_1", customer: "cus_1", status: "canceled" },
    );
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).toHaveBeenCalledTimes(1);
  });

  it("routes invoice.paid to the invoice handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent("invoice.paid", "evt_inv_1", {
      id: "in_1",
      customer: "cus_1",
      subscription: "sub_1",
      status: "paid",
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onInvoiceEvent).toHaveBeenCalledTimes(1);
  });

  it("routes invoice.payment_failed to the invoice handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent("invoice.payment_failed", "evt_inv_2", {
      id: "in_2",
      customer: "cus_1",
      subscription: "sub_1",
      status: "open",
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onInvoiceEvent).toHaveBeenCalledTimes(1);
  });

  it("routes checkout.session.completed to the checkout handler", async () => {
    const ctx = makeCtx();
    const event = mkEvent("checkout.session.completed", "evt_cs_1", {
      id: "cs_1",
      customer: "cus_1",
      client_reference_id: "org_1",
      mode: "subscription",
    });
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onCheckoutCompleted).toHaveBeenCalledTimes(1);
  });

  it("ignores unhandled event types without throwing", async () => {
    const ctx = makeCtx();
    const event = mkEvent(
      "payment_intent.succeeded" as Stripe.Event.Type,
      "evt_pi_1",
      { id: "pi_1" },
    );
    await expect(handleWebhookEvent(event, ctx)).resolves.toBeUndefined();
    expect(ctx.handlers.onSubscriptionEvent).not.toHaveBeenCalled();
    expect(ctx.handlers.onInvoiceEvent).not.toHaveBeenCalled();
    expect(ctx.handlers.onCheckoutCompleted).not.toHaveBeenCalled();
  });
});

describe("handleWebhookEvent — idempotency", () => {
  it("skips dispatch when the event id was already processed", async () => {
    // Second delivery: SET NX returns null, i.e. the key already existed.
    const ctx = makeCtx({ redisFirst: false });
    const event = mkEvent(
      "customer.subscription.updated",
      "evt_dup",
      { id: "sub_1", customer: "cus_1", status: "active" },
    );
    await handleWebhookEvent(event, ctx);
    expect(ctx.handlers.onSubscriptionEvent).not.toHaveBeenCalled();
  });

  it("uses a 7-day TTL on the idempotency key", async () => {
    const ctx = makeCtx();
    const event = mkEvent(
      "customer.subscription.created",
      "evt_ttl",
      { id: "sub_1", customer: "cus_1", status: "active" },
    );
    await handleWebhookEvent(event, ctx);
    const redisSet = ctx.redis!.set as ReturnType<typeof vi.fn>;
    expect(redisSet).toHaveBeenCalled();
    // Arguments: (key, value, "EX", ttlSeconds, "NX")
    const args = redisSet.mock.calls[0]!;
    expect(args[0]).toBe("stripe:webhook:evt_ttl");
    expect(args.includes("EX")).toBe(true);
    expect(args.includes(7 * 24 * 60 * 60)).toBe(true);
    expect(args.includes("NX")).toBe(true);
  });
});

describe("verifyAndParseEvent", () => {
  it("returns the parsed event when signature is valid", () => {
    const fakeEvent = mkEvent("customer.subscription.created", "evt_ok", {});
    const stripe = {
      webhooks: {
        constructEvent: vi.fn().mockReturnValue(fakeEvent),
      },
    } as never;
    const result = verifyAndParseEvent(
      { rawBody: Buffer.from("{}"), signature: "t=1,v1=abc" },
      { stripe, webhookSecret: "whsec_test" },
    );
    expect(result).toBe(fakeEvent);
    const constructFn = (stripe as { webhooks: { constructEvent: ReturnType<typeof vi.fn> } })
      .webhooks.constructEvent;
    expect(constructFn).toHaveBeenCalledWith(
      Buffer.from("{}"),
      "t=1,v1=abc",
      "whsec_test",
    );
  });

  it("throws when signature verification fails", () => {
    const stripe = {
      webhooks: {
        constructEvent: vi.fn().mockImplementation(() => {
          throw new Error("No signatures found matching the expected signature");
        }),
      },
    } as never;
    expect(() =>
      verifyAndParseEvent(
        { rawBody: Buffer.from("{}"), signature: "bad" },
        { stripe, webhookSecret: "whsec_test" },
      ),
    ).toThrow(/signature/i);
  });

  it("throws when the signature header is missing", () => {
    const stripe = {
      webhooks: { constructEvent: vi.fn() },
    } as never;
    expect(() =>
      verifyAndParseEvent(
        { rawBody: Buffer.from("{}"), signature: undefined },
        { stripe, webhookSecret: "whsec_test" },
      ),
    ).toThrow(/missing/i);
  });
});
