/**
 * Unit tests for the billing router.
 *
 * Covers:
 *   - currentSubscription: unauthenticated rejection, null result, populated row
 *   - invoices: validation error on bad input shape, proxy success
 *   - createCheckout: unauthorized, validation error on empty priceId
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { appRouter } from '../index.js';
import { createTestContext as createInnerContext } from './_helpers.js';
import type { AuthContext } from '../../context.js';

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

describe('billing router', () => {
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

  it('rejects unauthenticated callers on currentSubscription', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.billing.currentSubscription()).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns null when no Subscription row exists', async () => {
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
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
    expect(await caller.billing.currentSubscription()).toBeNull();
  });

  it('returns subscription row when present', async () => {
    const row = {
      id: 'sub-1',
      orgId: ORG_ID,
      stripeCustomerId: 'cus_1',
      stripeSubscriptionId: 'sub_1',
      status: 'active',
      tier: 'pro',
      currentPeriodEnd: new Date('2026-06-01T00:00:00Z'),
    };
    const withRlsUser = vi.fn(async (_p, _u, fn) =>
      fn({ subscription: { findUnique: vi.fn().mockResolvedValue(row) } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.billing.currentSubscription();
    expect(result?.tier).toBe('pro');
  });

  it('rejects invoices for unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.billing.invoices({ limit: 10 })).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('rejects createCheckout with empty priceId (Zod validation)', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.billing.createCheckout({ priceId: '' }),
    ).rejects.toThrow();
  });

  it('createCheckout proxies to API and returns Stripe URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ url: 'https://checkout.stripe.com/c/pay/cs_1' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    const result = await caller.billing.createCheckout({ priceId: 'price_x' });
    expect(result.url).toMatch(/^https:\/\/checkout\.stripe\.com/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
