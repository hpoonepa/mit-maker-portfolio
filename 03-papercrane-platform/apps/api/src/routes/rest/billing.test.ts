import Fastify from "fastify";
import sensible from "@fastify/sensible";
import { describe, expect, it, vi } from "vitest";
import { registerBillingRoutes } from "./billing.js";

/**
 * Billing route smoke tests.
 *
 * We stub the Stripe client (no network) and an in-memory prisma mock. The
 * goal is to verify routing, auth gating, body parsing, signature handling,
 * and raw-body preservation — not the downstream handler logic, which lives
 * in @papercrane/billing and is tested there.
 */

function buildApp(opts: {
  auth?: { orgId: string } | null;
  stripe?: unknown;
  prisma?: unknown;
  redis?: unknown;
  webhookSecret?: string;
}) {
  const app = Fastify({ logger: false });
  return app.register(sensible).then(async () => {
    // Minimal auth hook — populates req.auth from a test header so we don't
    // have to wire the real supabase/api-key resolver.
    app.addHook("preHandler", async (req) => {
      const routeConfig = req.routeOptions?.config as
        | { public?: boolean }
        | undefined;
      if (routeConfig?.public) return;
      if (opts.auth) {
        req.auth = {
          kind: "apiKey",
          apiKeyId: "k1",
          orgId: opts.auth.orgId,
          tier: "free",
          scopes: ["*"],
          prefix: "pc_test_",
        } as never;
      }
    });

    await registerBillingRoutes(app, {
      prisma: (opts.prisma ?? {
        subscription: {
          findUnique: vi.fn().mockResolvedValue(null),
        },
      }) as never,
      redis: (opts.redis ?? null) as never,
      stripe: (opts.stripe ?? {
        checkout: {
          sessions: {
            create: vi.fn().mockResolvedValue({
              id: "cs_1",
              url: "https://stripe.example/cs_1",
            }),
          },
        },
        billingPortal: {
          sessions: {
            create: vi.fn().mockResolvedValue({
              id: "bps_1",
              url: "https://stripe.example/bps_1",
            }),
          },
        },
        webhooks: { constructEvent: vi.fn() },
      }) as never,
      priceEnv: {
        STRIPE_PRICE_PRO_MONTHLY: "price_pro_monthly_test",
        STRIPE_PRICE_PRO_ANNUAL: "price_pro_annual_test",
        STRIPE_PRICE_SEAT_ADDON: "price_seat_addon_test",
        STRIPE_PRICE_PACK_10K: "price_pack_10k_test",
      },
      webhookSecret: opts.webhookSecret ?? "whsec_test",
    });

    return app;
  });
}

describe("POST /v1/billing/checkout", () => {
  it("returns 401 without auth", async () => {
    const app = await buildApp({ auth: null });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/checkout",
      payload: { priceId: "price_pro_monthly_test" },
    });
    expect(res.statusCode).toBeGreaterThanOrEqual(400);
    await app.close();
  });

  it("returns a checkout URL when authed", async () => {
    const prisma = {
      $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
        fn({
          subscription: {
            findUnique: vi.fn().mockResolvedValue(null),
          },
          $executeRaw: vi.fn().mockResolvedValue(undefined),
        }),
      ),
    };
    const app = await buildApp({
      auth: { orgId: "11111111-1111-1111-1111-111111111111" },
      prisma,
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/checkout",
      payload: { priceId: "price_pro_monthly_test" },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { url: string };
    expect(body.url).toMatch(/^https:\/\/stripe\.example/);
    await app.close();
  });

  it("rejects malformed body", async () => {
    const app = await buildApp({
      auth: { orgId: "11111111-1111-1111-1111-111111111111" },
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/checkout",
      payload: { priceId: "" },
    });
    expect(res.statusCode).toBeGreaterThanOrEqual(400);
    await app.close();
  });
});

describe("POST /v1/billing/portal", () => {
  it("401 without auth", async () => {
    const app = await buildApp({ auth: null });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/portal",
      payload: {},
    });
    expect(res.statusCode).toBeGreaterThanOrEqual(400);
    await app.close();
  });

  it("fails when the org has no Stripe customer yet", async () => {
    const prisma = {
      $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
        fn({
          subscription: {
            findUnique: vi.fn().mockResolvedValue(null),
          },
          $executeRaw: vi.fn().mockResolvedValue(undefined),
        }),
      ),
    };
    const app = await buildApp({
      auth: { orgId: "11111111-1111-1111-1111-111111111111" },
      prisma,
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/portal",
      payload: {},
    });
    expect(res.statusCode).toBeGreaterThanOrEqual(400);
    await app.close();
  });

  it("returns a portal URL when the org has a Stripe customer", async () => {
    const prisma = {
      $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) =>
        fn({
          subscription: {
            findUnique: vi
              .fn()
              .mockResolvedValue({ stripeCustomerId: "cus_123" }),
          },
          $executeRaw: vi.fn().mockResolvedValue(undefined),
        }),
      ),
    };
    const app = await buildApp({
      auth: { orgId: "11111111-1111-1111-1111-111111111111" },
      prisma,
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/portal",
      payload: { returnUrl: "https://app.example/billing" },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { url: string };
    expect(body.url).toMatch(/^https:\/\/stripe\.example/);
    await app.close();
  });
});

describe("POST /v1/billing/webhook", () => {
  it("rejects missing Stripe-Signature with 400", async () => {
    const app = await buildApp({ auth: null });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ id: "evt_1", type: "noop" }),
    });
    expect(res.statusCode).toBe(400);
    await app.close();
  });

  it("rejects bad signatures with 400", async () => {
    const app = await buildApp({
      auth: null,
      stripe: {
        checkout: { sessions: { create: vi.fn() } },
        billingPortal: { sessions: { create: vi.fn() } },
        webhooks: {
          constructEvent: vi.fn().mockImplementation(() => {
            throw new Error("No signatures found matching the expected signature");
          }),
        },
      },
    });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: {
        "content-type": "application/json",
        "stripe-signature": "t=1,v1=bad",
      },
      payload: JSON.stringify({ id: "evt_1", type: "noop" }),
    });
    expect(res.statusCode).toBe(400);
    await app.close();
  });

  it("dispatches a verified event and returns 200", async () => {
    const fakeEvent = {
      id: "evt_ok",
      type: "checkout.session.completed",
      data: { object: { id: "cs_x", customer: null, mode: "subscription" } },
    };
    const constructEvent = vi.fn().mockReturnValue(fakeEvent);
    const redisSet = vi.fn().mockResolvedValue("OK");
    const app = await buildApp({
      auth: null,
      redis: { set: redisSet } as never,
      stripe: {
        checkout: { sessions: { create: vi.fn() } },
        billingPortal: { sessions: { create: vi.fn() } },
        webhooks: { constructEvent },
      },
    });
    const payload = JSON.stringify({ id: "evt_ok", type: fakeEvent.type });
    const res = await app.inject({
      method: "POST",
      url: "/v1/billing/webhook",
      headers: {
        "content-type": "application/json",
        "stripe-signature": "t=1,v1=good",
      },
      payload,
    });
    expect(res.statusCode).toBe(200);
    // Verify the signature call received the raw bytes, not a re-serialized
    // JSON — this is the critical invariant for Stripe HMAC.
    const args = constructEvent.mock.calls[0]!;
    expect(Buffer.isBuffer(args[0])).toBe(true);
    expect((args[0] as Buffer).toString("utf8")).toBe(payload);
    expect(args[1]).toBe("t=1,v1=good");
    await app.close();
  });
});
