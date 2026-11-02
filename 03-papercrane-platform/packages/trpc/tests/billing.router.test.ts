import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

/**
 * Billing router — read-only `currentSubscription` / `invoices`, plus a
 * `createCheckout` mutation that proxies to the REST API
 * `POST /v1/billing/checkout` (the actual Stripe call lives server-side).
 *
 * We mock `withRlsUser` for the read queries and `fetch` for the mutation.
 */

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'free',
  scopes: ['*'],
};

describe('billing router — currentSubscription', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.billing.currentSubscription()).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns null when no Subscription row exists (free tier)', async () => {
    const withRlsUser = vi.fn(async (_prisma, _uid, fn) =>
      fn({
        subscription: { findUnique: vi.fn().mockResolvedValue(null) },
      }),
    );

    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const result = await caller.billing.currentSubscription();
    expect(result).toBeNull();
  });

  it('returns the Subscription mirror when one exists', async () => {
    const row = {
      id: 'sub-uuid',
      orgId: ORG_ID,
      stripeCustomerId: 'cus_abc',
      stripeSubscriptionId: 'sub_abc',
      status: 'active',
      tier: 'pro',
      currentPeriodEnd: new Date('2026-05-01T00:00:00Z'),
      createdAt: new Date('2026-04-01T00:00:00Z'),
      updatedAt: new Date('2026-04-10T00:00:00Z'),
    };
    const withRlsUser = vi.fn(async (_prisma, _uid, fn) =>
      fn({
        subscription: { findUnique: vi.fn().mockResolvedValue(row) },
      }),
    );

    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const result = await caller.billing.currentSubscription();
    expect(result).not.toBeNull();
    expect(result?.tier).toBe('pro');
    expect(result?.status).toBe('active');
  });
});

describe('billing router — invoices', () => {
  it('requires auth', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.billing.invoices({ limit: 10 })).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns items from the api proxy', async () => {
    const invoices = [
      {
        id: 'in_1',
        number: 'INV-0001',
        amountPaid: 29900,
        currency: 'usd',
        status: 'paid',
        created: new Date('2026-04-01T00:00:00Z').toISOString(),
        hostedInvoiceUrl: 'https://stripe.example/in_1',
        invoicePdf: 'https://stripe.example/in_1.pdf',
      },
    ];

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: invoices, nextCursor: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const origFetch = globalThis.fetch;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    try {
      const caller = appRouter.createCaller(
        createInnerContext({ auth: AUTH }),
      );
      const result = await caller.billing.invoices({ limit: 10 });
      expect(result.items).toHaveLength(1);
      expect(result.items[0]!.number).toBe('INV-0001');
    } finally {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (globalThis as any).fetch = origFetch;
    }
  });
});

describe('billing router — createCheckout', () => {
  const origFetch = globalThis.fetch;
  const origEnv = { ...process.env };

  beforeEach(() => {
    process.env.API_BASE_URL = 'http://api.test.local';
  });

  afterEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = origFetch;
    process.env = { ...origEnv };
  });

  it('requires auth', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.billing.createCheckout({ priceId: 'price_abc' }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('POSTs to /v1/billing/checkout and returns the Stripe url', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ url: 'https://checkout.stripe.com/c/pay/cs_test_1' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));

    const result = await caller.billing.createCheckout({
      priceId: 'price_abc',
      returnPath: '/settings/billing',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://api.test.local/v1/billing/checkout');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.priceId).toBe('price_abc');
    expect(result.url).toMatch(/^https:\/\/checkout\.stripe\.com/);
  });

  it('throws when the API returns an error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'price_unknown' }), {
        status: 400,
        headers: { 'content-type': 'application/json' },
      }),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.billing.createCheckout({ priceId: 'bad' }),
    ).rejects.toThrow();
  });
});
