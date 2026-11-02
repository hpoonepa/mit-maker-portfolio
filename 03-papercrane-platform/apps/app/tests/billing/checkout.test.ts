import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  redirectToCheckout,
  CheckoutError,
  type CheckoutClientDeps,
} from "@/lib/billing/checkout";

/**
 * The client helper is a thin proxy around `POST /v1/billing/checkout`. We
 * don't hit Stripe from the browser: the API server creates a Checkout
 * Session and returns the hosted URL. Our job is:
 *
 *   1. POST { priceId, returnUrl? } with the Supabase access token as Bearer
 *   2. Parse the { url } response
 *   3. window.location = url  (redirect the user to Stripe)
 *
 * We inject `fetch` and the navigator so jsdom tests can assert the redirect
 * without the test runner actually navigating away.
 */

const PRICE_ID = "price_1Pro_monthly_test";
const CHECKOUT_URL = "https://checkout.stripe.com/c/pay/cs_test_abc123";
const API_BASE = "http://localhost:3001";

function mockDeps(overrides: Partial<CheckoutClientDeps> = {}): {
  deps: CheckoutClientDeps;
  navigate: ReturnType<typeof vi.fn>;
  fetchMock: ReturnType<typeof vi.fn>;
} {
  const navigate = vi.fn();
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ url: CHECKOUT_URL }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  const deps: CheckoutClientDeps = {
    fetch: fetchMock as unknown as typeof fetch,
    navigate,
    getAccessToken: async () => "supabase-jwt-token",
    apiBaseUrl: API_BASE,
    ...overrides,
  };
  return { deps, navigate, fetchMock };
}

describe("redirectToCheckout", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs to /v1/billing/checkout with the price id + auth header", async () => {
    const { deps, fetchMock } = mockDeps();

    await redirectToCheckout({ priceId: PRICE_ID }, deps);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE}/v1/billing/checkout`);
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["content-type"]).toBe("application/json");
    expect(headers["authorization"]).toBe("Bearer supabase-jwt-token");
    expect(init.body).toBeDefined();
    const body = JSON.parse(init.body as string);
    expect(body.priceId).toBe(PRICE_ID);
  });

  it("includes a returnUrl when provided", async () => {
    const { deps, fetchMock } = mockDeps();

    await redirectToCheckout(
      { priceId: PRICE_ID, returnPath: "/settings/billing" },
      deps,
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    // The helper builds the fully-qualified URL from window.location.origin.
    expect(body.returnUrl).toContain("/settings/billing");
  });

  it("navigates the browser to the returned checkout URL", async () => {
    const { deps, navigate } = mockDeps();

    await redirectToCheckout({ priceId: PRICE_ID }, deps);

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(CHECKOUT_URL);
  });

  it("throws CheckoutError on non-2xx response", async () => {
    const { deps } = mockDeps({
      fetch: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "price_unknown" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        }),
      ) as unknown as typeof fetch,
    });

    await expect(
      redirectToCheckout({ priceId: "bad" }, deps),
    ).rejects.toBeInstanceOf(CheckoutError);
  });

  it("throws CheckoutError when the response is missing a url", async () => {
    const { deps } = mockDeps({
      fetch: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ) as unknown as typeof fetch,
    });

    await expect(
      redirectToCheckout({ priceId: PRICE_ID }, deps),
    ).rejects.toBeInstanceOf(CheckoutError);
  });

  it("omits authorization header when no access token is available", async () => {
    const { deps, fetchMock } = mockDeps({
      getAccessToken: async () => null,
    });

    await redirectToCheckout({ priceId: PRICE_ID }, deps);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["authorization"]).toBeUndefined();
  });
});
