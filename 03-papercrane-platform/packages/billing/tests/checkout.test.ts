import { describe, expect, it, vi } from "vitest";
import { createCheckoutSession } from "../src/checkout.js";
import { createPortalSession } from "../src/portal.js";

/**
 * Checkout / portal session creation. The interesting behavior lives in what
 * we pass to Stripe; we stub the Stripe client with vi.fn() and assert on the
 * arguments.
 */

function makeStripeStub(opts: {
  sessionUrl?: string;
  portalUrl?: string;
  stripeCustomerId?: string | null;
} = {}) {
  const sessionsCreate = vi.fn().mockResolvedValue({
    id: "cs_test_1",
    url: opts.sessionUrl ?? "https://stripe.example/checkout/cs_test_1",
  });
  const portalCreate = vi.fn().mockResolvedValue({
    id: "bps_test_1",
    url: opts.portalUrl ?? "https://stripe.example/portal/bps_test_1",
  });
  return {
    client: {
      checkout: { sessions: { create: sessionsCreate } },
      billingPortal: { sessions: { create: portalCreate } },
    } as never,
    sessionsCreate,
    portalCreate,
  };
}

describe("createCheckoutSession", () => {
  it("creates a subscription-mode session with the provided price and URLs", async () => {
    const { client, sessionsCreate } = makeStripeStub();

    const result = await createCheckoutSession(
      {
        orgId: "org_123",
        priceId: "price_pro_monthly_test",
        successUrl: "https://app.example/return?ok=1",
        cancelUrl: "https://app.example/return?ok=0",
      },
      { stripe: client },
    );

    expect(result.url).toMatch(/^https:\/\/stripe.example/);
    expect(sessionsCreate).toHaveBeenCalledTimes(1);
    const arg = sessionsCreate.mock.calls[0]![0] as {
      mode: string;
      line_items: Array<{ price: string; quantity: number }>;
      success_url: string;
      cancel_url: string;
      client_reference_id: string;
      metadata: Record<string, string>;
    };
    expect(arg.mode).toBe("subscription");
    expect(arg.line_items).toEqual([
      { price: "price_pro_monthly_test", quantity: 1 },
    ]);
    expect(arg.success_url).toBe("https://app.example/return?ok=1");
    expect(arg.cancel_url).toBe("https://app.example/return?ok=0");
    // org id must be on the session so the webhook can link customer→org.
    expect(arg.client_reference_id).toBe("org_123");
    expect(arg.metadata.orgId).toBe("org_123");
  });

  it("re-uses an existing Stripe customer when the org already has one", async () => {
    const { client, sessionsCreate } = makeStripeStub();

    await createCheckoutSession(
      {
        orgId: "org_123",
        priceId: "price_pro_monthly_test",
        successUrl: "https://app.example/ok",
        cancelUrl: "https://app.example/cancel",
        stripeCustomerId: "cus_existing",
      },
      { stripe: client },
    );

    const arg = sessionsCreate.mock.calls[0]![0] as {
      customer?: string;
      customer_email?: string;
    };
    expect(arg.customer).toBe("cus_existing");
    // When we pass a customer, we must NOT also pass customer_email — Stripe
    // rejects the combination.
    expect(arg.customer_email).toBeUndefined();
  });
});

describe("createPortalSession", () => {
  it("creates a Customer Portal session with the given return URL", async () => {
    const { client, portalCreate } = makeStripeStub();

    const result = await createPortalSession(
      {
        stripeCustomerId: "cus_test",
        returnUrl: "https://app.example/settings/billing",
      },
      { stripe: client },
    );

    expect(result.url).toMatch(/^https:\/\/stripe.example/);
    expect(portalCreate).toHaveBeenCalledTimes(1);
    expect(portalCreate.mock.calls[0]![0]).toEqual({
      customer: "cus_test",
      return_url: "https://app.example/settings/billing",
    });
  });
});
